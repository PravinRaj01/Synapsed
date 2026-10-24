"""Download the models the server loads at runtime, so they can be baked into the container image.

Run during the image build (see Dockerfile.vercel). It reads the model name from the app's settings, so the
image always holds whichever model PII_MALAY_MODEL names. Exits non-zero if a download fails, which fails the
build instead of shipping an image that would download at runtime.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.core.config import get_settings  # noqa: E402


def main() -> int:
    settings = get_settings()
    if not settings.pii_malay_model:
        print("PII_MALAY_MODEL is blank: nothing to download")
        return 0
    from transformers import AutoModelForTokenClassification, AutoTokenizer

    name = settings.pii_malay_model
    print(f"downloading {name} ...")
    AutoTokenizer.from_pretrained(name)
    AutoModelForTokenClassification.from_pretrained(name)
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
