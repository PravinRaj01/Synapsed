from langdetect import DetectorFactory, LangDetectException, detect

DetectorFactory.seed = 0  # make language detection deterministic


def detect_language(text: str) -> str | None:
    """ISO 639-1 code of the dominant language, or None when it cannot be told (e.g. very short text).

    langdetect cannot tell Malay from Indonesian reliably and usually answers "id" for Malay.
    """
    try:
        return detect(text[:2000])
    except LangDetectException:
        return None
