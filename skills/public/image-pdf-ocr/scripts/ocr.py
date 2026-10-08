#!/usr/bin/env python3
"""
OCR helper for the image-pdf-ocr skill.

Sends user-uploaded image/PDF files to the internal DeepSeek OCR-2 model
served by vLLM (OpenAI-compatible ``/v1/chat/completions`` API) and prints
the extracted markdown to stdout (so the agent can "read" the content).
PDFs are rendered page-by-page into images client-side before OCR.

Usage:
    python ocr.py --file <path> [--file <path> ...] \
        [--prompt "..." ] [--dpi 144] [--model deepseek-ai/DeepSeek-OCR-2] \
        [--max-tokens 4096] [--temperature 0] \
        [--pages "1-10,15"] [--to-files DIR] \
        [--base-url http://10.0.27.59:8002]

Exit code 0 on success, non-zero on error.
"""

import argparse
import base64
import os
import sys

import requests

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif", ".tiff", ".tif"}
PDF_EXTS = {".pdf"}

DEFAULT_BASE_URL = "http://10.0.27.59:8002"
DEFAULT_MODEL = "deepseek-ai/DeepSeek-OCR-2"
DEFAULT_PROMPT = "<image>\nConvert the document to markdown."

_IMAGE_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
}


def _classify(path: str) -> str:
    """Return 'image', 'pdf', or 'unknown' based on file extension."""
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in PDF_EXTS:
        return "pdf"
    return "unknown"


def _parse_page_spec(spec: str | None) -> set[int] | None:
    """Parse a 1-based page spec like '3', '1-10', '1-10,15,20-25' into a set.

    Returns None when spec is None (all pages).
    """
    if not spec:
        return None
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, _, end = part.partition("-")
            try:
                lo, hi = int(start), int(end)
            except ValueError:
                raise ValueError(f"bad page range: {part!r}")
            if lo < 1 or hi < lo:
                raise ValueError(f"bad page range: {part!r}")
            pages.update(range(lo, hi + 1))
        else:
            try:
                n = int(part)
            except ValueError:
                raise ValueError(f"bad page number: {part!r}")
            if n < 1:
                raise ValueError(f"bad page number: {part!r}")
            pages.add(n)
    return pages or None


def _get_pymupdf():
    """Import fitz, installing pymupdf on first use if needed (PDF rendering)."""
    try:
        import fitz
        return fitz
    except ImportError:
        print("[info] pymupdf not installed; installing...", file=sys.stderr)
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "pymupdf", "-q"], check=False)
        import fitz
        return fitz


def _image_bytes_as_png(path: str) -> tuple[bytes, str]:
    """Return (png_bytes, mime) for an image file.

    Prefer normalizing through PyMuPDF (already required for PDFs) so exotic
    formats (gif/tiff/bmp/...) become plain PNG. Falls back to raw bytes with
    a mime guessed from the extension.
    """
    try:
        fitz = _get_pymupdf()
        doc = fitz.open(path)
        try:
            pix = doc[0].get_pixmap()
            return pix.tobytes("png"), "image/png"
        finally:
            doc.close()
    except Exception:  # noqa: BLE001
        with open(path, "rb") as f:
            raw = f.read()
        mime = _IMAGE_MIME.get(os.path.splitext(path)[1].lower(), "image/jpeg")
        return raw, mime


def _pdf_pages_as_png(path: str, dpi: int, pages: set[int] | None):
    """Yield (page_number, png_bytes) for selected pages of a PDF."""
    fitz = _get_pymupdf()
    doc = fitz.open(path)
    try:
        for i, page in enumerate(doc):
            page_number = i + 1
            if pages is not None and page_number not in pages:
                continue
            pix = page.get_pixmap(dpi=dpi)
            yield page_number, pix.tobytes("png")
    finally:
        doc.close()


def _chat(base_url: str, model: str, prompt_text: str, image_b64: str, mime: str,
          max_tokens: int, temperature: float, timeout: int) -> str:
    """Send one image to the vLLM OpenAI-compatible chat endpoint; return text."""
    url = f"{base_url}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
                    {"type": "image_url",
                     "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                ],
            }
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    resp = requests.post(url, json=payload, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"OCR API returned HTTP {resp.status_code}: {resp.text[:500]}")
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"unexpected OCR API response: {str(data)[:500]}")


def ocr_image(path: str, base_url: str, model: str, prompt: str,
              max_tokens: int, temperature: float, timeout: int) -> str:
    png, mime = _image_bytes_as_png(path)
    b64 = base64.b64encode(png).decode("ascii")
    return _chat(base_url, model, prompt, b64, mime, max_tokens, temperature, timeout)


def ocr_pdf_pages(path: str, base_url: str, model: str, prompt: str, dpi: int,
                  max_tokens: int, temperature: float, timeout: int,
                  pages: set[int] | None = None):
    """OCR selected PDF pages sequentially; yield (page_number, markdown)."""
    for page_number, png in _pdf_pages_as_png(path, dpi, pages):
        b64 = base64.b64encode(png).decode("ascii")
        text = _chat(base_url, model, prompt, b64, "image/png",
                     max_tokens, temperature, timeout)
        yield page_number, text


def _save_page_files(path: str, out_dir: str, results) -> list[str]:
    """Write per-page markdown to ``out_dir/<pdfstem>_page_NN.md``."""
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(path))[0]
    saved = []
    for page_number, text in results:
        dest = os.path.join(out_dir, f"{stem}_page_{page_number:02d}.md")
        with open(dest, "w", encoding="utf-8") as f:
            f.write(f"<!-- page {page_number} -->\n{text}")
        saved.append((dest, len(text)))
    return saved


def main() -> int:
    parser = argparse.ArgumentParser(description="OCR user-uploaded image/PDF files.")
    parser.add_argument("--file", action="append", required=True,
                        help="Path to an image or PDF file (repeatable).")
    parser.add_argument("--prompt", default=None,
                        help="Optional override prompt sent to the OCR model.")
    parser.add_argument("--dpi", type=int, default=144,
                        help="PDF render DPI (default: 144). Lower it if pages are rejected for length.")
    parser.add_argument("--pages", default=None,
                        help="PDF only: page spec like '3', '1-10', '1-10,15,20-25' (default: all pages).")
    parser.add_argument("--to-files", default=None, metavar="DIR",
                        help="PDF only: save each page's markdown to DIR/<pdfname>_page_NN.md "
                             "instead of printing everything to stdout (keeps the context small).")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"Served model name (default: {DEFAULT_MODEL}).")
    parser.add_argument("--max-tokens", type=int, default=4096,
                        help="Max output tokens per page/image (default: 4096).")
    parser.add_argument("--temperature", type=float, default=0.0,
                        help="Sampling temperature (default: 0.0).")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL,
                        help=f"vLLM OpenAI-compatible base URL (default: {DEFAULT_BASE_URL}).")
    args = parser.parse_args()

    try:
        page_filter = _parse_page_spec(args.pages)
    except ValueError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1

    prompt = f"<image>\n{args.prompt}" if args.prompt else DEFAULT_PROMPT

    any_error = False
    for path in args.file:
        if not os.path.isfile(path):
            print(f"[error] file not found: {path}", file=sys.stderr)
            any_error = True
            continue

        kind = _classify(path)
        try:
            if kind == "image":
                text = ocr_image(path, args.base_url, args.model, prompt,
                                 args.max_tokens, args.temperature, timeout=300)
                print(f"\n===== IMAGE OCR: {os.path.basename(path)} =====")
                print(text or "(no text extracted)")
            elif kind == "pdf":
                if args.to_files:
                    results = list(ocr_pdf_pages(
                        path, args.base_url, args.model, prompt, args.dpi,
                        args.max_tokens, args.temperature, timeout=300,
                        pages=page_filter))
                    saved = _save_page_files(path, args.to_files, results)
                    print(f"===== PDF OCR: {os.path.basename(path)} "
                          f"({len(saved)} pages saved to {args.to_files}) =====")
                    for dest, chars in saved:
                        print(f"[saved] {dest} ({chars} chars)")
                else:
                    results = list(ocr_pdf_pages(
                        path, args.base_url, args.model, prompt, args.dpi,
                        args.max_tokens, args.temperature, timeout=300,
                        pages=page_filter))
                    parts = [f"<!-- page {page_number} -->\n{text}"
                             for page_number, text in results]
                    print(f"\n===== PDF OCR: {os.path.basename(path)} ({len(results)} pages) =====")
                    print("\n\n".join(parts) or "(no text extracted)")
            else:
                print(f"[error] unsupported file type: {path} "
                      f"(supported: {', '.join(sorted(IMAGE_EXTS | PDF_EXTS))})",
                      file=sys.stderr)
                any_error = True
                continue
        except Exception as e:  # noqa: BLE001
            print(f"[error] OCR failed for {path}: {e}", file=sys.stderr)
            any_error = True

    return 1 if any_error else 0


if __name__ == "__main__":
    sys.exit(main())
