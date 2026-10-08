# DeepSeek OCR-2 (vLLM) API Reference

Base URL: `http://10.0.27.59:8002` (internal network, no auth).
Server: vLLM OpenAI-compatible server (`vllm-openai`), model
`deepseek-ai/DeepSeek-OCR-2`.

## Endpoints

### `GET /health`

vLLM health check — returns HTTP 200 when the server is up.

### `GET /v1/models`

Lists served models (confirm `deepseek-ai/DeepSeek-OCR-2` is loaded).

### `POST /v1/chat/completions`

OCR one image. The image is passed as a base64 **data URI** inside a chat
message whose text contains the `<image>` placeholder.

**Request JSON:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `model` | string | ✅ | `deepseek-ai/DeepSeek-OCR-2` |
| `messages` | array | ✅ | One user message with `content` = `[{type: "text", text: "<image>\n<instruction>"}, {type: "image_url", image_url: {url: "data:<mime>;base64,<b64>"}}]` |
| `temperature` | number | | Sampling temperature (default 0.0 recommended) |
| `max_tokens` | number | | Max output tokens (server max-model-len is 8192) |

**Response (standard OpenAI chat-completion shape):**

```json
{
  "choices": [
    {
      "message": {
        "role": "assistant",
        "content": "...extracted markdown text..."
      }
    }
  ],
  "usage": {
    "prompt_tokens": 1234,
    "completion_tokens": 567
  }
}
```

The field you care about is `choices[0].message.content`.

## PDF handling

vLLM does **not** accept PDFs directly — the model input is a single image per
request. The helper script (`scripts/ocr.py`) renders PDF pages to PNG images
client-side with pymupdf (`--dpi`, default 144) and OCRs them one page at a
time, joining the results with `<!-- page N -->` markers.

## Prompt format

- Default prompt: `<image>\nConvert the document to markdown.`
- The `<image>` token marks where the image is placed.
- To override, pass `--prompt "..."` (the helper prepends `<image>\n`), or
  change the text content in a direct `curl` call.
- A grounding mode exists (`<|grounding|>`) that annotates output with
  bounding-box coordinates — useful when positions matter, noisier otherwise.

## Notes

- Not available (removed with the old FastAPI server): embedded/cropped image
  extraction, bounding-box annotated image, and layout PDF output. The vLLM
  endpoint returns text only.
- Server flags worth knowing: `--max-model-len 8192`,
  `--max-num-batched-tokens 8192`, `--max-num-seqs 8`. Requests that exceed
  the model length are rejected with HTTP 400 — lower the PDF `--dpi` or
  `--max-tokens`, or have the operator raise the vLLM limits.
- Preferred image formats: JPEG and PNG. The helper normalizes other formats
  through pymupdf; pass JPEG/PNG directly when calling the API by hand.
