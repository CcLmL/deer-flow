---
name: image-pdf-ocr
description: Read the text content of user-uploaded images and PDFs using the internal DeepSeek OCR-2 model (served by vLLM, OpenAI-compatible API). Trigger when the user uploads an image (jpg/png/webp/bmp/gif/tiff) or PDF and wants its contents extracted, read, transcribed, summarized, or used as context — including "look at this picture", "read this PDF", "what does this image say", "帮我看看这张图/这个PDF", "识别图片/提取文字", or when a task depends on understanding what's in an uploaded image or PDF. Handles both single images and multi-page PDFs, returns extracted markdown text.
---

# Image & PDF OCR Skill

Read the text content of user-uploaded images and PDFs by sending them to the
internal **DeepSeek OCR-2** model served by vLLM at `http://10.0.27.59:8002`
(OpenAI-compatible `/v1/chat/completions` API, model name
`deepseek-ai/DeepSeek-OCR-2`). The model extracts the text (and structure) from
images/PDFs and returns it as markdown, so you can actually "read" what the
user uploaded.

This is a standard **OpenAI-compatible HTTP JSON API** — call it with whatever
HTTP tool is in your environment (`curl`, `requests`, etc.). A helper Python
script (`scripts/ocr.py`) is provided for convenience and handles image
encoding plus client-side PDF page rendering.

## When to invoke

Use this skill when the user uploads an image or PDF and needs its **content**:

- "帮我看看这张图片 / 这个图片里有什么"
- "read / extract / OCR this image or PDF"
- "识别这张图 / 提取图片里的文字"
- "what does this PDF say / summarize this PDF"
- "look at the screenshot I sent / check the chart in this image"
- Any task where you must understand text embedded in an uploaded image or PDF

**Do NOT use** for plain text files, code files, or Excel/CSV data — those have
their own handling. Only for **images** and **PDFs**.

## Where user files live

User-uploaded files are under `/mnt/user-data/uploads/`. Locate the specific
file(s) by extension or name, e.g.:

```bash
ls -R /mnt/user-data/uploads/ | grep -iE "\.(png|jpe?g|webp|bmp|gif|tif|pdf)$"
```

## Quick start

Use the helper script — it auto-detects image vs PDF and prints the extracted text:

```bash
python /mnt/skills/public/image-pdf-ocr/scripts/ocr.py \
  --file /mnt/user-data/uploads/photo.jpg

# multiple files at once
python /mnt/skills/public/image-pdf-ocr/scripts/ocr.py \
  --file /mnt/user-data/uploads/a.png \
  --file /mnt/user-data/uploads/report.pdf
```

The extracted markdown is printed to stdout. **Read it and use it** as the
content of the uploaded file when answering the user.

### Optional flags

| Flag | Description |
|------|-------------|
| `--prompt "..."` | Override the OCR model's prompt (e.g. ask it to extract a table, translate, or focus on something specific) |
| `--dpi 144` | PDF render DPI (default 144). **Lower it** (e.g. 100) if pages are rejected with a length error |
| `--pages "1-10,15"` | PDF only: OCR only the given pages (default: all pages) |
| `--to-files DIR` | PDF only: save each page's markdown to `DIR/<pdfname>_page_NN.md` instead of printing to stdout — keeps the conversation context small |
| `--max-tokens 4096` | Max output tokens per page/image (default 4096) |
| `--temperature 0` | Sampling temperature (default 0.0) |
| `--model ...` | Served model name (default `deepseek-ai/DeepSeek-OCR-2`) |
| `--base-url ...` | API base URL (default `http://10.0.27.59:8002`) |

## Large / multi-page PDFs — MUST read

A full-book OCR in one shot will exceed the sandbox bash timeout (600s) and
flood the conversation context with page text, which corrupts the run. For any
PDF with more than ~10 pages:

1. **Process in chunks.** Run the helper once per batch of pages:

   ```bash
   python /mnt/skills/public/image-pdf-ocr/scripts/ocr.py \
     --file /mnt/user-data/uploads/report.pdf --pages "1-10" --to-files /mnt/user-data/outputs/ocr
   ```

2. **Prefer `--to-files`.** Each page lands in its own `.md` file; then use
   `grep` / `read_file` on the files to answer the user. Never dump whole-book
   markdown into stdout.
3. If a page range call approaches the 600s bash limit, use smaller batches
   (e.g. 5 pages) — each call is a fresh timeout.
4. Before OCR-ing, check whether the PDF has a text layer: translated
   documents usually do, and direct text extraction with pymupdf is orders of
   magnitude faster than OCR and uses no GPU. For "which pages are untranslated"
   style checks, prefer text-layer statistics over full OCR.

## Direct curl usage

The helper wraps this endpoint; you can also call it directly:

```bash
BASE=http://10.0.27.59:8002

# health check (200 = healthy)
curl -s $BASE/health

# OCR a single image — base64 data URI inside a chat message
IMG_B64=$(base64 -w0 /mnt/user-data/uploads/photo.jpg)
curl -s $BASE/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d "{
    \"model\": \"deepseek-ai/DeepSeek-OCR-2\",
    \"messages\": [{
      \"role\": \"user\",
      \"content\": [
        {\"type\": \"text\", \"text\": \"<image>\\nConvert the document to markdown.\"},
        {\"type\": \"image_url\", \"image_url\": {\"url\": \"data:image/jpeg;base64,$IMG_B64\"}}
      ]
    }],
    \"temperature\": 0,
    \"max_tokens\": 4096
  }"
```

## Handling the response

The API returns a standard OpenAI chat-completion JSON. The field you care
about is `choices[0].message.content` — the extracted markdown text.
(`usage.prompt_tokens` / `usage.completion_tokens` are also present.)

For PDFs, the helper renders each page to an image and OCRs it sequentially;
the printed markdown contains `<!-- page N -->` markers so you know which page
text came from. Multi-page PDFs are therefore slower (one request per page).

Use the returned text as the readable content. If it is empty, say so honestly
(e.g. a blank/scan-only image) rather than guessing.

## Workflow

1. **Locate the file(s)** under `/mnt/user-data/uploads/`.
2. **Run the helper script** (or `curl`) for each image/PDF.
3. **Read the returned markdown** — this is the file's content.
4. **Answer the user** using that content. If the user asked to summarize,
   translate, extract data, or act on the content, do so now.

## Notes

- The API is on the internal network; no auth is required.
- The helper script uses `requests` and `pymupdf` (for PDF rendering); pymupdf
  is auto-installed via pip on first use if missing.
- Timeout: each request uses a 300s timeout. Large multi-page PDFs process
  page-by-page and can take a while.
- The vLLM server is configured with `--max-model-len 8192`. If a request is
  rejected with a length/model-limit error (HTTP 400), retry with a lower
  `--dpi` for PDFs, or reduce `--max-tokens`; for persistent problems ask the
  operator to raise vLLM's `--max-model-len`.
- If the API is unreachable, first check `curl -s $BASE/health` for status.
