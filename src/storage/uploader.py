"""
Media Uploader
Uploads audio files to Cloudinary and returns a public URL.
Cloudinary free tier: 25 GB storage, 25 GB bandwidth/month — more than enough.
"""

import logging
from pathlib import Path

import cloudinary
import cloudinary.uploader

logger = logging.getLogger(__name__)


class MediaUploader:
    def __init__(self, settings):
        cloudinary.config(
            cloud_name=settings.cloudinary_cloud_name,
            api_key=settings.cloudinary_api_key,
            api_secret=settings.cloudinary_api_secret,
            secure=True,
        )

    async def upload_audio(self, audio_path: Path) -> str:
        """
        Upload MP3 to Cloudinary.

        Returns:
            Public HTTPS URL of the uploaded audio.
        """
        result = cloudinary.uploader.upload(
            str(audio_path),
            resource_type="video",      # Cloudinary uses "video" for audio files
            folder="content-pipeline/audio",
            overwrite=False,
            invalidate=True,
        )
        url: str = result["secure_url"]
        logger.info("Audio uploaded to Cloudinary: %s", url)

        # Clean up local tmp file
        try:
            audio_path.unlink()
        except OSError:
            pass

        return url
