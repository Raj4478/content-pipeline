"""
Voice Generator
Converts script text to MP3 using ElevenLabs multilingual v2.
Saves audio to a temp file and returns the path.
"""

import logging
import uuid
from pathlib import Path

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class VoiceGenerator:
    BASE_URL = "https://api.elevenlabs.io/v1"

    def __init__(self, settings):
        self.settings = settings
        self.out_dir = settings.audio_tmp_dir

    async def generate(self, text: str, voice_id: str) -> Path:
        """
        Generate voiceover MP3 for given text.

        Args:
            text:     The full narration script (~150 words)
            voice_id: ElevenLabs voice ID

        Returns:
            Path to the saved MP3 file
        """
        audio_bytes = await self._call_elevenlabs(text=text, voice_id=voice_id)
        out_path = self.out_dir / f"voice_{uuid.uuid4().hex[:8]}.mp3"
        out_path.write_bytes(audio_bytes)
        logger.info("Audio saved: %s (%d KB)", out_path, len(audio_bytes) // 1024)
        return out_path

    @retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=3, max=15),
    )
    async def _call_elevenlabs(self, text: str, voice_id: str) -> bytes:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self.BASE_URL}/text-to-speech/{voice_id}",
                headers={
                    "xi-api-key": self.settings.elevenlabs_api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "text": text,
                    "model_id": self.settings.elevenlabs_model_id,
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.75,
                        "style": 0.3,           # adds a bit of expressiveness
                        "use_speaker_boost": True,
                    },
                },
            )
            resp.raise_for_status()
            return resp.content

    async def list_voices(self) -> list[dict]:
        """Helper to browse available voices during setup."""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.BASE_URL}/voices",
                headers={"xi-api-key": self.settings.elevenlabs_api_key},
            )
            resp.raise_for_status()
            return resp.json()["voices"]
