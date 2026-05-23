"""
Local Video Renderer — MoviePy + ffmpeg-python based, zero cost.
No ImageMagick needed. Avoids segfault by using ffmpeg for resize.
"""

import logging
import math
import textwrap
import uuid
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import requests
import numpy as np

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("tmp/videos")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TARGET_W = 1080
TARGET_H = 1920
FPS = 30
CAPTION_FONT_SIZE = 52
HOOK_FONT_SIZE = 64
CAPTION_STROKE_WIDTH = 3
CAPTION_Y_POSITION = 0.70
HOOK_Y_POSITION = 0.12
WORDS_PER_CAPTION = 6


@dataclass
class RenderResult:
    render_id: str
    video_url: str
    width: int
    height: int
    duration: float


class LocalVideoRenderer:
    def __init__(self, settings):
        self.settings = settings

    async def render(
        self,
        template_id: str,
        hook_text: str,
        body_text: str,
        video_url: str,
        audio_url: str,
        bg_music_path: Optional[str] = None,
    ) -> RenderResult:
        from moviepy.editor import (
            VideoFileClip, AudioFileClip, CompositeVideoClip,
            ImageClip, concatenate_videoclips,
        )

        render_id = uuid.uuid4().hex[:10]
        logger.info("LocalRenderer [%s] starting render", render_id)

        # ── 1. Download footage ────────────────────────────────────────
        footage_path = self._download_file(video_url, suffix=".mp4", label="footage")
        logger.info("[%s] Footage downloaded: %s", render_id, footage_path)

        # ── 2. Use ffmpeg to crop + scale to 9:16 (avoids segfault) ───
        processed_path = OUTPUT_DIR / f"proc_{render_id}.mp4"
        self._ffmpeg_crop_vertical(footage_path, processed_path)
        logger.info("[%s] Footage processed to vertical: %s", render_id, processed_path)

        # ── 3. Load audio ──────────────────────────────────────────────
        audio_path = self._resolve_audio(audio_url, render_id)
        audio_clip = AudioFileClip(str(audio_path))
        total_duration = audio_clip.duration
        logger.info("[%s] Audio duration: %.1fs", render_id, total_duration)

        # ── 4. Load + loop processed footage ──────────────────────────
        base_clip = VideoFileClip(str(processed_path), audio=False)
        if base_clip.duration < total_duration:
            loops = math.ceil(total_duration / base_clip.duration)
            logger.info("[%s] Looping footage %dx", render_id, loops)
            footage = concatenate_videoclips([base_clip] * loops)
        else:
            footage = base_clip
        footage = footage.subclip(0, total_duration)

        # ── 5. Attach audio ────────────────────────────────────────────
        video_with_audio = footage.set_audio(audio_clip)

        # ── 6. Build PIL captions ──────────────────────────────────────
        caption_clips = self._build_captions(
            hook_text=hook_text,
            body_text=body_text,
            total_duration=total_duration,
            ImageClip=ImageClip,
        )

        # ── 7. Composite ───────────────────────────────────────────────
        layers = [video_with_audio] + caption_clips
        final = CompositeVideoClip(layers, size=(TARGET_W, TARGET_H))
        final = final.set_duration(total_duration)

        # ── 8. Export ──────────────────────────────────────────────────
        out_path = OUTPUT_DIR / f"video_{render_id}.mp4"
        logger.info("[%s] Exporting to %s ...", render_id, out_path)
        final.write_videofile(
            str(out_path),
            fps=FPS,
            codec="libx264",
            audio_codec="aac",
            bitrate="4000k",
            audio_bitrate="192k",
            threads=4,
            preset="fast",
            logger=None,
        )

        # ── Cleanup ────────────────────────────────────────────────────
        self._cleanup([footage_path, processed_path])
        audio_clip.close()
        final.close()

        logger.info("[%s] Render complete: %s", render_id, out_path)
        return RenderResult(
            render_id=render_id,
            video_url=str(out_path),
            width=TARGET_W,
            height=TARGET_H,
            duration=total_duration,
        )

    # ── ffmpeg crop to 9:16 ────────────────────────────────────────────
    def _ffmpeg_crop_vertical(self, src: Path, dst: Path) -> None:
        """
        Use ffmpeg directly to crop + scale footage to 1080x1920.
        This avoids MoviePy's resize() which segfaults on Windows
        with certain numpy/PIL combos.
        
        ffmpeg filter: 
          crop to 9:16 aspect ratio first, then scale to target.
        """
        # vf: crop to portrait keeping centre, then scale
        vf = (
            f"crop='if(gt(iw/ih,9/16),ih*9/16,iw)':'if(gt(iw/ih,9/16),ih,iw*16/9)',"
            f"scale={TARGET_W}:{TARGET_H}:flags=lanczos"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", str(src),
            "-vf", vf,
            "-an",                      # drop audio — we overlay ours
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            str(dst)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error("ffmpeg crop failed: %s", result.stderr[-500:])
            raise RuntimeError(f"ffmpeg crop failed:\n{result.stderr[-300:]}")

    # ── Caption system (PIL, no ImageMagick) ───────────────────────────
    def _build_captions(self, hook_text, body_text, total_duration, ImageClip) -> list:
        clips = []

        hook_duration = min(4.0, total_duration * 0.15)
        clips.append(
            self._make_pil_caption(
                text=hook_text,
                font_size=HOOK_FONT_SIZE,
                duration=hook_duration,
                y_pos=HOOK_Y_POSITION,
                color=(255, 220, 0),
                ImageClip=ImageClip,
            ).set_start(0)
        )

        body_start = hook_duration
        body_duration = total_duration - body_start
        words = body_text.split()
        if not words:
            return clips

        chunks = [
            " ".join(words[i: i + WORDS_PER_CAPTION])
            for i in range(0, len(words), WORDS_PER_CAPTION)
        ]
        chunk_duration = body_duration / len(chunks)

        for idx, chunk in enumerate(chunks):
            clips.append(
                self._make_pil_caption(
                    text=chunk,
                    font_size=CAPTION_FONT_SIZE,
                    duration=chunk_duration,
                    y_pos=CAPTION_Y_POSITION,
                    color=(255, 255, 255),
                    ImageClip=ImageClip,
                ).set_start(body_start + idx * chunk_duration)
            )

        return clips

    def _make_pil_caption(self, text, font_size, duration, y_pos, color, ImageClip):
        from PIL import Image, ImageDraw, ImageFont

        wrapped_lines = textwrap.wrap(text, width=26) or [text]
        stroke = CAPTION_STROKE_WIDTH

        font = None
        for fp in [
            "arial.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/calibri.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]:
            try:
                font = ImageFont.truetype(fp, font_size)
                break
            except (IOError, OSError):
                continue
        if font is None:
            font = ImageFont.load_default()

        scratch = Image.new("RGBA", (1, 1))
        draw = ImageDraw.Draw(scratch)
        bboxes = [draw.textbbox((0, 0), line, font=font) for line in wrapped_lines]
        lh = [bb[3] - bb[1] for bb in bboxes]
        lw = [bb[2] - bb[0] for bb in bboxes]
        gap = int(font_size * 0.25)

        total_h = sum(lh) + gap * max(0, len(wrapped_lines) - 1) + stroke * 2 + 10
        total_w = max(lw) + stroke * 2 + 20

        img = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        y_c = stroke + 5
        for i, line in enumerate(wrapped_lines):
            x_c = (total_w - lw[i]) // 2
            for dx in range(-stroke, stroke + 1):
                for dy in range(-stroke, stroke + 1):
                    if dx or dy:
                        draw.text((x_c + dx, y_c + dy), line, font=font, fill=(0, 0, 0, 255))
            draw.text((x_c, y_c), line, font=font, fill=(*color, 255))
            y_c += lh[i] + gap

        arr = np.array(img)
        x = (TARGET_W - total_w) // 2
        y = max(0, min(int(TARGET_H * y_pos - total_h / 2), TARGET_H - total_h))

        return ImageClip(arr, ismask=False).set_duration(duration).set_position((x, y))

    # ── Helpers ────────────────────────────────────────────────────────
    def _download_file(self, url: str, suffix: str, label: str) -> Path:
        tmp_path = OUTPUT_DIR / f"tmp_{uuid.uuid4().hex[:8]}{suffix}"
        resp = requests.get(url, stream=True, timeout=60)
        resp.raise_for_status()
        with open(tmp_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 256):
                f.write(chunk)
        return tmp_path

    def _resolve_audio(self, audio_url: str, render_id: str) -> Path:
        if audio_url.startswith("http"):
            return self._download_file(audio_url, suffix=".mp3", label="audio")
        path = Path(audio_url)
        if not path.exists():
            raise FileNotFoundError(f"Audio not found: {audio_url}")
        return path

    def _cleanup(self, paths):
        for p in paths:
            try:
                if p and Path(p).exists():
                    Path(p).unlink()
            except OSError:
                pass
