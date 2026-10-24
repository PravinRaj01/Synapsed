"""Build data/demo/embeddings.json.gz: one vector for every demo text, so loading the demo needs no API call.

Run after editing data/demo/demo.json (needs GEMINI_API_KEY). Texts that already have a vector are not sent again.
"""

import gzip
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from ai_pipeline.embedder import embed_texts  # noqa: E402
from app.demo import DATA, embedded_texts, load_definition, load_embeddings, text_key  # noqa: E402

DECIMALS = 5


def main() -> int:
    texts = embedded_texts(load_definition())
    stored = load_embeddings()
    wanted = {text_key(t) for t in texts}
    missing = [t for t in texts if text_key(t) not in stored]
    print(f"{len(texts)} texts, {len(missing)} to embed")
    if missing:
        for text, vector in zip(missing, embed_texts(missing)):
            stored[text_key(text)] = [round(x, DECIMALS) for x in vector]
    kept = {key: vector for key, vector in stored.items() if key in wanted}  # drop vectors of texts that were edited away
    with gzip.open(DATA / "embeddings.json.gz", "wt", encoding="utf-8") as handle:
        json.dump(kept, handle, separators=(",", ":"))
    print(f"wrote {len(kept)} vectors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
