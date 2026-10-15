"""Text extraction in a CHILD process: bytes on stdin -> one JSON object on stdout.  `python -I -B extract_child.py <pdf|docx>`

Why a child: this is the one place the server parses a file an attacker may have crafted. A pure-Python PDF parse holds the GIL (it would
stall every request of the single uvicorn worker) and a thread cannot be killed, so the parent starts this script, gives it a wall-clock
deadline and kills it on timeout. It is STANDALONE on purpose (stdlib + pypdf, no `app` imports): `-I` drops the working directory from
sys.path, the parent gives it an EMPTY environment (no SESSION_SECRET, no API keys, no DATABASE_URL), and before touching the input it
caps its own memory / CPU / file writes and, if it runs as root (the image does), drops to `nobody`.
"""

import io
import json
import os
import re
import sys

MAX_TEXT = 200_000          # characters returned
MAX_PAGES = 8               # PDF pages read
MAX_XML = 12 * 1024 * 1024  # DOCX: bytes of word/document.xml we are willing to read (a zip bomb lies about its sizes, so we bound the READ)
MAX_ZIP_ENTRIES = 2000


def _lock_down() -> None:
    try:
        import resource
        gb = 1024 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (gb, gb))
        resource.setrlimit(resource.RLIMIT_CPU, (5, 6))        # a real resume parses in well under a second; a crafted PDF is cut off long before the parent's 8 s wall
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
        resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    except Exception:
        pass
    try:
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            os.setgroups([])
            os.setgid(65534)
            os.setuid(65534)
    except Exception:
        pass


def _out(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=True))     # ASCII-only JSON: no dependence on the (ignored, under -I) PYTHONIOENCODING
    sys.stdout.flush()


def _pdf(data: bytes) -> dict:
    try:
        from pypdf import PdfReader
    except Exception:
        return {"ok": False, "error": "extract_unavailable"}
    try:
        r = PdfReader(io.BytesIO(data), strict=False)
        if r.is_encrypted:
            try:
                ok = r.decrypt("")                      # many PDFs are "encrypted" with an empty user password
            except Exception:
                ok = 0
            if not ok:
                return {"ok": False, "error": "encrypted"}
        total = len(r.pages)
        parts = []
        for i in range(min(total, MAX_PAGES)):
            try:
                parts.append(r.pages[i].extract_text() or "")
            except Exception:
                parts.append("")
        warnings = [f"only the first {MAX_PAGES} of {total} pages were read"] if total > MAX_PAGES else []
        return {"ok": True, "text": "\n\n".join(parts)[:MAX_TEXT], "pages": total, "warnings": warnings}
    except Exception:
        return {"ok": False, "error": "bad_file"}


_TOKEN = re.compile(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>|(</w:p>)|(</w:tc>)|<w:tab\s*/>|<w:br\s*/>|<w:cr\s*/>")


def _unescape(s: str) -> str:
    import html
    return html.unescape(s)


def _docx(data: bytes) -> dict:
    import zipfile
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        infos = zf.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            return {"ok": False, "error": "bad_file"}
        names = {i.filename for i in infos}
        if "word/document.xml" not in names:
            return {"ok": False, "error": "bad_file"}
        with zf.open("word/document.xml") as fh:
            xml = fh.read(MAX_XML + 1)
        if len(xml) > MAX_XML:
            return {"ok": False, "error": "bad_file"}
    except Exception:
        return {"ok": False, "error": "bad_file"}
    s = xml.decode("utf-8", errors="replace")
    out = []
    for m in _TOKEN.finditer(s):
        if m.group(1) is not None:
            out.append(_unescape(m.group(1)))
        elif m.group(2):
            out.append("\n")
        elif m.group(3):
            out.append("  |  ")
        else:
            tag = m.group(0)
            out.append("\t" if tag.startswith("<w:tab") else "\n")
    text = "".join(out)
    lines, prev = [], None
    for ln in text.split("\n"):             # text boxes appear twice (AlternateContent Choice + Fallback): drop immediate repeats
        ln = ln.rstrip()
        if ln and ln == prev:
            continue
        lines.append(ln)
        prev = ln or prev
    return {"ok": True, "text": "\n".join(lines)[:MAX_TEXT], "pages": 0, "warnings": []}


def main() -> None:
    kind = sys.argv[1] if len(sys.argv) > 1 else ""
    _lock_down()
    data = sys.stdin.buffer.read()
    if kind == "pdf":
        _out(_pdf(data))
    elif kind == "docx":
        _out(_docx(data))
    else:
        _out({"ok": False, "error": "bad_file"})


if __name__ == "__main__":
    main()
