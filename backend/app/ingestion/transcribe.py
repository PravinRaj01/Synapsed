"""Speech-to-text through Groq Whisper (free tier, 25 MB per request).

ffmpeg converts anything to small mono MP3 pieces so long recordings and videos fit.
Without ffmpeg, an audio file under the size limit is sent as-is; video needs ffmpeg.
"""

import subprocess
import tempfile
from pathlib import Path, PurePath
import shutil

from groq import Groq

from app.core.config import get_settings
from app.ingestion.parsers import AUDIO_EXT, IngestError, ToolMissing

DIRECT_LIMIT = 24 * 1024 * 1024
SEGMENT_SECONDS = 600  # at 32 kbps a 10-minute piece is about 2.4 MB


def _groq() -> Groq:
    key = get_settings().groq_api_key
    if not key:
        raise IngestError("GROQ_API_KEY is not set, so audio cannot be transcribed")
    return Groq(api_key=key)


def _transcribe_piece(name: str, data: bytes) -> str:
    result = _groq().audio.transcriptions.create(
        file=(name, data), model=get_settings().groq_model_whisper, response_format="text"
    )
    return (result if isinstance(result, str) else getattr(result, "text", "")).strip()


def _split_with_ffmpeg(data: bytes, filename: str) -> list[tuple[str, bytes]]:
    suffix = PurePath(filename).suffix or ".bin"
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"input{suffix}"
        src.write_bytes(data)
        pattern = str(Path(tmp) / "part_%03d.mp3")
        proc = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000",
             "-b:a", "32k", "-f", "segment", "-segment_time", str(SEGMENT_SECONDS), pattern],
            capture_output=True, text=True, timeout=600,
        )
        if proc.returncode != 0:
            raise IngestError(f"ffmpeg could not read the file: {proc.stderr.strip()[:200]}")
        parts = sorted(Path(tmp).glob("part_*.mp3"))
        if not parts:
            raise IngestError("No audio track was found in the file")
        return [(p.name, p.read_bytes()) for p in parts]


def transcribe(data: bytes, filename: str) -> str:
    ext = PurePath(filename).suffix.lower()
    if shutil.which("ffmpeg"):
        pieces = _split_with_ffmpeg(data, filename)
    elif ext in AUDIO_EXT and len(data) <= DIRECT_LIMIT:
        pieces = [(PurePath(filename).name, data)]
    elif ext in AUDIO_EXT:
        raise ToolMissing("ffmpeg is not installed, and this audio file is too large to send directly.")
    else:
        raise ToolMissing("ffmpeg is not installed, so video files cannot be processed.")
    text = "\n\n".join(t for t in (_transcribe_piece(n, d) for n, d in pieces) if t)
    if not text.strip():
        raise IngestError("No speech was detected in the recording")
    return text
