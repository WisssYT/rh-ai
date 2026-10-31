"""Isolated PDF text extractor.

Run as:  python -I pdf_worker.py <path> <max_pages> <max_chars>
It only imports the standard library and pypdf, never executes PDF JavaScript,
never follows links or fetches resources, and prints one JSON object to stdout.
The parent process applies a wall-clock timeout plus CPU/memory rlimits.
"""

import json
import sys


def main() -> None:
    path, max_pages, max_chars = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    out = {"ok": False, "error": None, "page_count": 0, "pages": [], "flags": [], "truncated": False}
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        try:
            reader = PdfReader(path, strict=False)
        except PdfReadError as e:
            out["error"] = f"malformed_pdf: {type(e).__name__}"
            print(json.dumps(out))
            return
        if reader.is_encrypted:
            out["error"] = "encrypted_pdf_unsupported"
            print(json.dumps(out))
            return
        n = len(reader.pages)
        out["page_count"] = n
        if n > max_pages:
            out["error"] = f"too_many_pages: {n} > {max_pages}"
            print(json.dumps(out))
            return
        total = 0
        for i, page in enumerate(reader.pages, start=1):
            try:
                txt = page.extract_text() or ""
            except Exception as e:  # noqa: BLE001 - untrusted input; record and continue
                out["flags"].append(f"page_{i}_extract_error:{type(e).__name__}")
                txt = ""
            if total + len(txt) > max_chars:
                txt = txt[: max(0, max_chars - total)]
                out["truncated"] = True
            total += len(txt)
            out["pages"].append({"page": i, "text": txt})
            if out["truncated"]:
                break
        out["ok"] = True
    except Exception as e:  # noqa: BLE001
        out["error"] = f"parser_failure: {type(e).__name__}"
    print(json.dumps(out))


if __name__ == "__main__":
    main()
