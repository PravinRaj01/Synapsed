"""Speech-to-text through Groq Whisper (free tier, 25 MB per request).

The file goes to Groq as-is: audio and video alike, in any format Groq accepts. There is no
ffmpeg on the server. A recording over the limit is split or compressed in the browser
(ffmpeg.wasm) before it is uploaded.
"""

from pathlib import PurePath

from groq import Groq

from app.core.config import get_settings
from app.ingestion.parsers import IngestError, ToolMissing

SEND_LIMIT = 24 * 1024 * 1024  # Groq's free tier allows 25 MB; keep a margin for the request
GROQ_FORMATS = {".flac", ".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".ogg", ".wav", ".webm"}
SAME_CONTAINER = {".mov": ".mp4"}  # QuickTime and MP4 share a container; Groq reads it under the mp4 name


def _groq() -> Groq:
    key = get_settings().groq_api_key
    if not key:
        raise ToolMissing("GROQ_API_KEY is not set, so audio cannot be transcribed.")
    return Groq(api_key=key)


def transcribe(data: bytes, filename: str) -> str:
    name = PurePath(filename).name
    ext = PurePath(filename).suffix.lower()
    if ext in SAME_CONTAINER:
        ext = SAME_CONTAINER[ext]
        name = PurePath(filename).stem + ext
    if ext not in GROQ_FORMATS:
        raise IngestError(
            f"Speech-to-text cannot read '{ext}' files. Convert it to mp3, m4a, wav, mp4 or webm first."
        )
    if len(data) > SEND_LIMIT:
        raise IngestError(
            "This recording is over 24 MB, the most the speech-to-text service accepts in one file. "
            "Compress or split it, then upload the parts."
        )
    result = _groq().audio.transcriptions.create(
        file=(name, data), model=get_settings().groq_model_whisper, response_format="text"
    )
    text = (result if isinstance(result, str) else getattr(result, "text", "")).strip()
    if not text:
        raise IngestError("No speech was detected in the recording")
    return text
