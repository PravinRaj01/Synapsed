"""Print the analysis pipeline as a Mermaid diagram (for the README or a slide).

    python scripts/export_diagram.py              # to the terminal
    python scripts/export_diagram.py pipeline.mmd # to a file
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from ai_pipeline.analysis.diagram import describe  # noqa: E402

if __name__ == "__main__":
    text = describe()["mermaid"]
    if len(sys.argv) > 1:
        pathlib.Path(sys.argv[1]).write_text(text, encoding="utf-8")
        print(f"wrote {sys.argv[1]}")
    else:
        print(text)
