"""
Content Automation Pipeline — Main Orchestrator
Generates, renders, and publishes finance/story Reels automatically.
"""

import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.generators.script_generator import ScriptGenerator
from src.generators.video_asset_fetcher import VideoAssetFetcher
from src.renderers.voice_generator import VoiceGenerator
from src.renderers.local_video_renderer import LocalVideoRenderer as VideoRenderer
from src.publishers.buffer_publisher import BufferPublisher
from src.storage.uploader import MediaUploader
from src.storage.run_tracker import RunTracker
from config.settings import Settings
from config.topics import TopicBank

logger = logging.getLogger(__name__)


async def run_pipeline(
    niche: str = "finance",
    topic: Optional[str] = None,
    dry_run: bool = False,
) -> dict:
    """
    End-to-end pipeline: script → voice → video → publish.

    Args:
        niche:   "finance" or "story"
        topic:   Optional override. If None, auto-picks from TopicBank.
        dry_run: Generate + render but skip publishing. For testing.

    Returns:
        result dict with status, video_url, post_id, and metadata.
    """
    settings = Settings()
    tracker = RunTracker(settings.db_path)
    run_id = tracker.start_run(niche=niche)

    logger.info("Run %s started | niche=%s dry_run=%s", run_id, niche, dry_run)

    try:
        # ── 1. Pick topic ──────────────────────────────────────────────
        topic_bank = TopicBank()
        selected_topic = topic or topic_bank.pick_unused(niche)
        logger.info("Topic selected: %s", selected_topic)

        # ── 2. Generate script ─────────────────────────────────────────
        generator = ScriptGenerator(settings)
        script = await generator.generate(niche=niche, topic=selected_topic)
        logger.info("Script generated | hook=%s", script.hook[:50])

        # ── 3. Fetch stock video ───────────────────────────────────────
        fetcher = VideoAssetFetcher(settings)
        video_asset = await fetcher.fetch(query=script.visual_query, niche=niche)
        logger.info("Video asset fetched: %s", video_asset.url)

        # ── 4. Generate voiceover ──────────────────────────────────────
        voice_gen = VoiceGenerator(settings)
        audio_path = await voice_gen.generate(
            text=script.full_narration,
            voice_id=settings.elevenlabs_voice_id,
        )
        logger.info("Voiceover generated: %s", audio_path)

        # ── 5. Render video locally (MoviePy) — no CDN upload needed ─────
        renderer = VideoRenderer(settings)
        render_result = await renderer.render(
            template_id="",
            hook_text=script.hook,
            body_text=script.body,
            video_url=video_asset.url,
            audio_url=str(audio_path),
        )
        audio_url = str(audio_path)
        logger.info("Video rendered: %s", render_result.video_url)
        logger.info("Video rendered: %s", render_result.video_url)

        # ── 7. Publish ─────────────────────────────────────────────────
        post_ids: dict = {}
        if not dry_run:
            publisher = BufferPublisher(settings)
            caption = script.build_caption(niche=niche)
            post_ids = await publisher.publish(
                video_url=render_result.video_url,
                caption=caption,
                channels=settings.buffer_channels,
            )
            logger.info("Published | post_ids=%s", post_ids)
        else:
            logger.info("Dry run — skipping publish")

        # ── 8. Track success ───────────────────────────────────────────
        result = {
            "run_id": run_id,
            "status": "success",
            "niche": niche,
            "topic": selected_topic,
            "hook": script.hook,
            "video_url": render_result.video_url,
            "audio_url": audio_url,
            "post_ids": post_ids,
            "dry_run": dry_run,
            "timestamp": datetime.utcnow().isoformat(),
        }
        tracker.complete_run(run_id, result)
        topic_bank.mark_used(niche, selected_topic)
        return result

    except Exception as exc:
        logger.exception("Pipeline failed on run %s: %s", run_id, exc)
        tracker.fail_run(run_id, str(exc))
        raise


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Content automation pipeline")
    parser.add_argument("--niche", choices=["finance", "story"], default="finance")
    parser.add_argument("--topic", type=str, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(
                Path("logs") / f"pipeline_{datetime.utcnow().strftime('%Y%m%d')}.log"
            ),
        ],
    )

    result = asyncio.run(
        run_pipeline(
            niche=args.niche,
            topic=args.topic,
            dry_run=args.dry_run,
        )
    )
    print(f"\n✓ Done | video: {result['video_url']}")


if __name__ == "__main__":
    main()
