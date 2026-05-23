"""
Buffer Publisher
Queues video posts to Instagram and YouTube via Buffer API.
"""

import logging
from typing import Optional

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class BufferPublisher:
    BASE_URL = "https://api.bufferapp.com/1"

    def __init__(self, settings):
        self.settings = settings
        self._token = settings.buffer_access_token

    async def publish(
        self,
        video_url: str,
        caption: str,
        channels: list[str],
    ) -> dict[str, str]:
        """
        Queue a video post on all configured Buffer channels.

        Returns:
            Dict mapping channel_id → buffer_update_id
        """
        if not channels:
            logger.warning("No Buffer channels configured — skipping publish")
            return {}

        results: dict[str, str] = {}
        for channel_id in channels:
            try:
                update_id = await self._queue_post(
                    channel_id=channel_id,
                    video_url=video_url,
                    caption=caption,
                )
                results[channel_id] = update_id
                logger.info("Queued on channel %s → update %s", channel_id, update_id)
            except Exception as exc:
                logger.error("Failed to queue on channel %s: %s", channel_id, exc)

        return results

    @retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def _queue_post(
        self,
        channel_id: str,
        video_url: str,
        caption: str,
    ) -> str:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{self.BASE_URL}/updates/create.json",
                data={
                    "access_token": self._token,
                    "profile_ids[]": channel_id,
                    "text": caption,
                    "media[video]": video_url,
                    "scheduled_at": "",     # empty = add to queue at optimal time
                    "now": "false",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            if not data.get("success"):
                raise RuntimeError(f"Buffer rejected post: {data.get('message')}")

            updates = data.get("updates", [{}])
            return updates[0].get("id", "unknown")
