"""
Local Video Renderer — 100% ffmpeg, no Python image libs.
Styled captions with semi-transparent background box.
No segfaults. No ImageMagick.
"""

import logging, math, textwrap, uuid, subprocess, shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import requests

logger = logging.getLogger(__name__)
OUTPUT_DIR = Path("tmp/videos")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
TARGET_W, TARGET_H, FPS = 1080, 1920, 30
CAPTION_FONT_SIZE = 58
HOOK_FONT_SIZE = 68
CAPTION_Y_POSITION = 0.72
HOOK_Y_POSITION = 0.10
WORDS_PER_CAPTION = 5      # fewer words = bigger text = more readable

@dataclass
class RenderResult:
    render_id: str
    video_url: str
    width: int
    height: int
    duration: float

def _get_ffmpeg():
    ff = shutil.which("ffmpeg")
    if ff: return ff
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        raise RuntimeError("ffmpeg not found. Run: pip install imageio-ffmpeg")

class LocalVideoRenderer:
    def __init__(self, settings):
        self.settings = settings
        self._ffmpeg = _get_ffmpeg()
        logger.info("Using ffmpeg: %s", self._ffmpeg)

    async def render(self, template_id, hook_text, body_text, video_url, audio_url, bg_music_path=None):
        rid = uuid.uuid4().hex[:10]
        logger.info("LocalRenderer [%s] starting render", rid)

        footage = self._download_file(video_url, ".mp4", "footage")
        audio = self._resolve_audio(audio_url, rid)
        dur = self._get_duration(audio)
        logger.info("[%s] Audio duration: %.1fs", rid, dur)

        cropped = OUTPUT_DIR / f"crop_{rid}.mp4"
        self._crop(footage, cropped)
        logger.info("[%s] Cropped to vertical", rid)

        looped = OUTPUT_DIR / f"loop_{rid}.mp4"
        self._loop(cropped, looped, dur)
        logger.info("[%s] Looped footage", rid)

        out = OUTPUT_DIR / f"video_{rid}.mp4"
        self._burn_styled_captions(looped, audio, hook_text, body_text, dur, out)
        logger.info("[%s] Render complete: %s", rid, out)

        self._cleanup([footage, cropped, looped])
        return RenderResult(rid, str(out), TARGET_W, TARGET_H, dur)

    def _crop(self, src, dst):
        vf = (f"crop='if(gt(iw/ih,9/16),ih*9/16,iw)':'if(gt(iw/ih,9/16),ih,iw*16/9)',"
              f"scale={TARGET_W}:{TARGET_H}:flags=lanczos")
        self._ff(["-y","-i",str(src),"-vf",vf,"-an","-c:v","libx264","-preset","fast","-crf","23",str(dst)])

    def _loop(self, src, dst, dur):
        cd = self._get_duration(src)
        loops = max(1, math.ceil(dur / cd))
        self._ff(["-y","-stream_loop",str(loops),"-i",str(src),"-t",str(dur),"-c","copy",str(dst)])

    def _burn_styled_captions(self, video, audio, hook_text, body_text, dur, out):
        """
        Styled captions using ffmpeg drawbox + drawtext combo.
        Semi-transparent black box behind white text — Instagram style.
        """
        font = self._find_font()
        filters = []

        # ── Hook — yellow bold text, top of screen ─────────────────────
        hook_duration = min(4.0, dur * 0.15)
        hook_clean = self._clean(hook_text)
        hook_lines = textwrap.wrap(hook_text, width=22) or [hook_text]
        hook_line_h = HOOK_FONT_SIZE + 10
        hook_box_h = len(hook_lines) * hook_line_h + 30
        hook_box_y = int(TARGET_H * HOOK_Y_POSITION)
        hook_text_y = hook_box_y + 15

        # Background box for hook
        filters.append(
            f"drawbox="
            f"x=40:y={hook_box_y}:"
            f"w={TARGET_W - 80}:h={hook_box_h}:"
            f"color=black@0.55:t=fill:"
            f"enable='between(t,0,{hook_duration:.2f})'"
        )
        # Hook text (yellow, bold border)
        for i, line in enumerate(hook_lines):
            line_clean = self._clean(line)
            y = hook_text_y + i * hook_line_h
            filters.append(
                f"drawtext=fontfile='{font}'"
                f":text='{line_clean}'"
                f":fontsize={HOOK_FONT_SIZE}"
                f":fontcolor=#FFE234"
                f":borderw=2:bordercolor=black@0.8"
                f":x=(w-text_w)/2:y={y}"
                f":enable='between(t,0,{hook_duration:.2f})'"
            )

        # ── Body captions — white text, bottom third ───────────────────
        words = body_text.split()
        if words:
            chunks = [" ".join(words[i:i+WORDS_PER_CAPTION])
                      for i in range(0, len(words), WORDS_PER_CAPTION)]
            chunk_dur = (dur - hook_duration) / len(chunks)
            cap_y_base = int(TARGET_H * CAPTION_Y_POSITION)
            cap_line_h = CAPTION_FONT_SIZE + 12
            cap_padding = 20

            for i, chunk in enumerate(chunks):
                t_start = hook_duration + i * chunk_dur
                t_end = t_start + chunk_dur
                enable = f"between(t,{t_start:.3f},{t_end:.3f})"

                lines = textwrap.wrap(chunk, width=24) or [chunk]
                box_h = len(lines) * cap_line_h + cap_padding * 2
                box_y = cap_y_base - cap_padding

                # Semi-transparent background box
                filters.append(
                    f"drawbox="
                    f"x=30:y={box_y}:"
                    f"w={TARGET_W - 60}:h={box_h}:"
                    f"color=black@0.6:t=fill:"
                    f"enable='{enable}'"
                )

                # Caption text lines
                for j, line in enumerate(lines):
                    line_clean = self._clean(line)
                    y = cap_y_base + j * cap_line_h
                    filters.append(
                        f"drawtext=fontfile='{font}'"
                        f":text='{line_clean}'"
                        f":fontsize={CAPTION_FONT_SIZE}"
                        f":fontcolor=white"
                        f":borderw=2:bordercolor=black@0.9"
                        f":x=(w-text_w)/2:y={y}"
                        f":enable='{enable}'"
                    )

        self._ff([
            "-y",
            "-i", str(video),
            "-i", str(audio),
            "-vf", ",".join(filters),
            "-map", "0:v",
            "-map", "1:a",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k",
            "-t", str(dur),
            str(out)
        ])

    def _find_font(self):
        for f in [
            "C:/Windows/Fonts/arialbd.ttf",     # Arial Bold
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/calibrib.ttf",    # Calibri Bold
            "C:/Windows/Fonts/calibri.ttf",
            "C:/Windows/Fonts/verdana.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]:
            if Path(f).exists():
                return f.replace("\\", "/").replace("C:/", "C\\:/")
        raise RuntimeError("No font found.")

    def _clean(self, text):
        for ch in ["'", ":", "\\", "[", "]", "=", ",", "%", "\"", "{"  , "}"]:
            text = text.replace(ch, " ")
        return text.strip()

    def _ff(self, args):
        cmd = [self._ffmpeg] + args
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed:\n{result.stderr[-600:]}")

    def _get_duration(self, path):
        fp = shutil.which("ffprobe") or str(Path(self._ffmpeg).parent / "ffprobe")
        try:
            r = subprocess.run(
                [fp, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                capture_output=True, text=True)
            return float(r.stdout.strip())
        except Exception:
            from moviepy.editor import AudioFileClip
            c = AudioFileClip(str(path)); d = c.duration; c.close(); return d

    def _download_file(self, url, suffix, label):
        p = OUTPUT_DIR / f"tmp_{uuid.uuid4().hex[:8]}{suffix}"
        r = requests.get(url, stream=True, timeout=60)
        r.raise_for_status()
        with open(p, "wb") as f:
            for chunk in r.iter_content(1024 * 256): f.write(chunk)
        return p

    def _resolve_audio(self, url, rid):
        if url.startswith("http"):
            return self._download_file(url, ".mp3", "audio")
        p = Path(url)
        if not p.exists(): raise FileNotFoundError(f"Audio not found: {url}")
        return p

    def _cleanup(self, paths):
        for p in paths:
            try:
                if p and Path(p).exists(): Path(p).unlink()
            except Exception:
                pass
