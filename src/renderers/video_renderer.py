"""
Video Renderer
Submits a render job to Creatomate and polls until complete.
"""

import asyncio
import logging
from dataclasses import dataclass

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 5
MAX_POLL_ATTEMPTS = 60      # 5 min max wait for render


@dataclass
class RenderResult:
    render_id: str
    video_url: str
    width: int
    height: int
    duration: float


class VideoRenderer:
    def __init__(self, settings):
        self.settings = settings
        self._headers = {
            "Authorization": f"Bearer {self.settings.creatomate_api_key}",
            "Content-Type": "application/json",
        }

    async def render(
        self,
        template_id: str,
        hook_text: str,
        body_text: str,
        video_url: str,
        audio_url: str,
    ) -> RenderResult:
        """
        Submit render job and wait for completion.
        Raises RuntimeError if render fails or times out.
        """
        render_id = await self._submit_render(
            template_id=template_id,
            hook_text=hook_text,
            body_text=body_text,
            video_url=video_url,
            audio_url=audio_url,
        )
        logger.info("Render submitted: %s", render_id)
        return await self._poll_until_done(render_id)

    @retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=8),
    )
    async def _submit_render(
        self,
        template_id: str,
        hook_text: str,
        body_text: str,
        video_url: str,
        audio_url: str,
    ) -> str:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.settings.creatomate_base_url}/renders",
                headers=self._headers,
                json={
                    "template_id": template_id,
                    "modifications": {
                        "hook_text": hook_text,
                        "body_text": body_text,
                        "video_url": video_url,
                        "audio_url": audio_url,
                    },
                },
            )
            resp.raise_for_status()
            renders = resp.json()
            return renders[0]["id"]

    async def _poll_until_done(self, render_id: str) -> RenderResult:
        for attempt in range(MAX_POLL_ATTEMPTS):
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            status = await self._get_render_status(render_id)

            if status["status"] == "succeeded":
                logger.info("Render complete: %s", render_id)
                return RenderResult(
                    render_id=render_id,
                    video_url=status["url"],
                    width=status.get("width", 1080),
                    height=status.get("height", 1920),
                    duration=status.get("duration", 60.0),
                )
            if status["status"] == "failed":
                raise RuntimeError(
                    f"Creatomate render {render_id} failed: {status.get('error_message')}"
                )

            logger.debug(
                "Render %s: %s (attempt %d/%d)",
                render_id, status["status"], attempt + 1, MAX_POLL_ATTEMPTS,
            )

        raise TimeoutError(f"Render {render_id} did not complete within the time limit.")

    async def _get_render_status(self, render_id: str) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.settings.creatomate_base_url}/renders/{render_id}",
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()
