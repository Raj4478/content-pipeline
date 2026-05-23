"""
Video Asset Fetcher
Searches Pexels for relevant stock footage and returns a usable URL.
"""

import logging
import random
from dataclasses import dataclass

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

FALLBACK_QUERIES = {
    "finance": ["money coins", "city business", "laptop working"],
    "story": ["people talking", "city night", "dramatic sky"],
}


@dataclass
class VideoAsset:
    url: str
    width: int
    height: int
    duration: int
    pexels_id: int


class VideoAssetFetcher:
    BASE_URL = "https://api.pexels.com/videos/search"

    def __init__(self, settings):
        self.settings = settings

    async def fetch(self, query: str, niche: str = "finance") -> VideoAsset:
        """Fetch a vertical (portrait) stock video. Falls back on empty results."""
        try:
            asset = await self._search(query)
            if asset:
                return asset
            logger.warning("No results for '%s', trying fallback query", query)
        except Exception as exc:
            logger.warning("Pexels fetch failed for '%s': %s", query, exc)

        # Fallback: try a generic query for the niche
        fallback_query = random.choice(FALLBACK_QUERIES.get(niche, ["nature landscape"]))
        logger.info("Using fallback query: %s", fallback_query)
        return await self._search(fallback_query, required=True)

    @retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=8),
    )
    async def _search(self, query: str, required: bool = False) -> VideoAsset | None:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                self.BASE_URL,
                headers={"Authorization": self.settings.pexels_api_key},
                params={
                    "query": query,
                    "orientation": "portrait",   # vertical = 9:16 for Reels
                    "size": "medium",
                    "per_page": 10,
                },
            )
            resp.raise_for_status()
            videos = resp.json().get("videos", [])

        if not videos:
            if required:
                raise RuntimeError(f"No Pexels results for required query: '{query}'")
            return None

        # Pick a random video from results for variety
        video = random.choice(videos[:5])

        # Prefer HD portrait file
        files = video.get("video_files", [])
        portrait_files = [
            f for f in files
            if f.get("width", 0) < f.get("height", 1)  # portrait check
            and f.get("quality") in ("hd", "sd")
        ]
        chosen = portrait_files[0] if portrait_files else files[0]

        return VideoAsset(
            url=chosen["link"],
            width=chosen.get("width", 1080),
            height=chosen.get("height", 1920),
            duration=video.get("duration", 60),
            pexels_id=video["id"],
        )
