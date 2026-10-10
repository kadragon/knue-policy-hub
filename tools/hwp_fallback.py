"""Convert a complete HWP v5 file in a bounded subprocess.

Use transforms directly: pyhwp's CLI logs some parse failures but exits zero.
The raw record pass supplies a separate text inventory for loss checks.
"""

from __future__ import annotations

import json
import sys
from contextlib import closing
from io import BytesIO
from pathlib import Path


def convert(path: Path) -> dict:
    from hwp5.binmodel import Hwp5File as RecordFile, ParaText
    from hwp5.hwp5html import HTMLTransform
    from hwp5.xmlmodel import Hwp5File

    paragraphs = []
    with closing(RecordFile(str(path))) as source:
        flags = source.header.flags
        if any(getattr(flags, flag) for flag in ("password", "distributable", "drm", "cert_encrypted", "cert_drm")):
            raise RuntimeError("Protected HWP is unsupported")
        sections = list(source.bodytext)
        if not sections:
            raise RuntimeError("HWP has no body sections")
        for section in sections:
            for model in source.bodytext[section].models():
                # Image/shape objects cannot be represented faithfully in RAW Markdown.
                if model["type"].__name__.startswith("Shape"):
                    raise RuntimeError("HWP contains unsupported drawing content")
                if model["type"] is ParaText:
                    text = "".join(chunk for _, chunk in model["content"]["chunks"] if isinstance(chunk, str))
                    if text.strip():
                        paragraphs.append(text)
    if not paragraphs:
        raise RuntimeError("HWP has no source text")
    output = BytesIO()
    with closing(Hwp5File(str(path))) as source:
        HTMLTransform().transform_hwp5_to_xhtml(source, output)
    return {"html": output.getvalue().decode("utf-8"), "paragraphs": paragraphs}


if __name__ == "__main__":
    json.dump(convert(Path(sys.argv[1])), sys.stdout, ensure_ascii=False)
