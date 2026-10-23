"""Read text out of images and scanned PDFs with Gemini (vision / PDF input).

The file goes to Gemini as-is, before PII scrubbing (scrubbing needs text first); everything
after this step works on the scrubbed text. Replaces the Tesseract binary, which a serverless
host cannot install.
"""

from functools import lru_cache

from google import genai
from google.genai import errors, types

from app.core.config import get_settings
from app.ingestion.parsers import IngestError, ToolMissing

INLINE_LIMIT = 18 * 1024 * 1024  # Gemini accepts about 20 MB of inline data per request
PROMPT = (
    "Transcribe all the text in this file exactly as written, in its original language "
    "(English, Malay or others). Keep the reading order and line breaks. Do not translate, "
    "summarise or add commentary. If there is no readable text, reply with exactly NO_TEXT."
)
NO_TEXT = "NO_TEXT"
MIME_BY_EXT = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
    ".bmp": "image/bmp", ".tif": "image/tiff", ".tiff": "image/tiff", ".pdf": "application/pdf",
}


@lru_cache
def _client() -> genai.Client:
    return genai.Client(api_key=get_settings().google_api_key)


def read_text(data: bytes, mime_type: str) -> str:
    """Text found in an image or PDF. Raises IngestError when there is none."""
    if not get_settings().google_api_key:
        raise ToolMissing("GOOGLE_API_KEY is not set, so images and scanned PDFs cannot be read.")
    if len(data) > INLINE_LIMIT:
        raise IngestError("This file is too large to read (the limit is 18 MB for images and scanned PDFs)")
    try:
        response = _client().models.generate_content(
            model=get_settings().gemini_model,
            contents=[types.Part.from_bytes(data=data, mime_type=mime_type), PROMPT],
            config=types.GenerateContentConfig(temperature=0),
        )
    except errors.ClientError as exc:
        if exc.code == 400:
            raise IngestError("Gemini could not read this file") from exc
        raise IngestError(f"Text recognition is unavailable right now (HTTP {exc.code}). Try again shortly.") from exc
    except errors.APIError as exc:
        raise IngestError(f"Text recognition is unavailable right now (HTTP {exc.code}). Try again shortly.") from exc
    text = (response.text or "").strip()
    if not text or text == NO_TEXT:
        raise IngestError("No text was found in the file")
    return text
