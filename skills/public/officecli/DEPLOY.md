# OfficeCLI skill — deployment notes

Internal deployment guide for the `officecli` public skill. The `SKILL.md` is
what the agent reads; this file is for the operator.

## What this adds

- One offline binary for **Word `.docx`**, **Excel `.xlsx`**, and
  **PowerPoint `.pptx`**: create, read, edit, validate, query, batch, and
  format-preserving text replacement.
- Replaces the image-only `ppt-generation` path for intranet use, and
  supersedes the earlier `office-documents` skill.
- No sandbox image rebuild and no provisioner allowlist change: the binary
  rides the existing `skills/public` → projection → `/mnt/skills/public`
  delivery path.

## Version and integrity

| Item | Value |
| --- | --- |
| OfficeCLI version | `1.0.157` |
| Linux x64 binary size | `35,448,677` bytes |
| Linux x64 SHA-256 | `f8eefe88dbfa7464bee421e5421efe57fc26bc3180b30e56eef58594c8245c94` |
| License | Apache-2.0 (see `LICENSE`, `NOTICE`, `THIRD-PARTY-NOTICES.txt`) |
| Platform | Linux x86-64, glibc (`ELF 64-bit LSB pie executable`) |

The binary is **not committed to git**. `.gitignore` excludes
`skills/public/officecli/bin/officecli` and the Windows test binary. The
wrapper verifies the SHA-256 before the first use in each sandbox cache.

## Files

```text
skills/public/officecli/
├── SKILL.md                 # agent instructions
├── DEPLOY.md                # this file
├── LICENSE                  # Apache-2.0
├── NOTICE                   # upstream notice
├── THIRD-PARTY-NOTICES.txt  # upstream dependencies
└── bin/
    ├── officecli.sh         # committed launcher (POSIX sh, LF)
    └── officecli            # Linux x64 binary, gitignored, copied out-of-band
```

The Windows `officecli-win-x64.exe` used for local QA is **not** deployed.

## 1. Obtain the binary

On a machine with internet access, download the pinned release and verify it:

```bash
curl -fL -o officecli-linux-x64 \
  https://github.com/iOfficeAI/OfficeCLI/releases/download/v1.0.157/officecli-linux-x64
sha256sum officecli-linux-x64
# expected:
# f8eefe88dbfa7464bee421e5421efe57fc26bc3180b30e56eef58594c8245c94  officecli-linux-x64
```

If the upstream release asset name or URL changes, use the v1.0.157 asset and
keep the checksum check. Do not substitute a different version without updating
both `VERSION` and `EXPECTED_SHA256` in `bin/officecli.sh`.

## 2. Copy the skill to the production checkout

The production compose file mounts the host `skills/` directory into the
Gateway (`../skills:/app/skills:ro`), so the source of truth is the host
checkout:

```bash
REPO=/path/to/deer-flow          # production checkout
cd "$REPO"

# Copy the text files (SKILL.md, DEPLOY.md, licenses, wrapper) with the repo.
# Then place the binary out-of-band:
install -m 0644 /path/to/officecli-linux-x64 \
  "$REPO/skills/public/officecli/bin/officecli"
chmod 0755 "$REPO/skills/public/officecli/bin/officecli.sh"

sha256sum "$REPO/skills/public/officecli/bin/officecli"
ls -l "$REPO/skills/public/officecli/bin/"
```

If you transfer the wrapper from Windows, ensure it stays **LF**. A CRLF shell
script fails on Linux even when invoked with `sh`:

```bash
file skills/public/officecli/bin/officecli.sh   # should say "POSIX shell script"
# If it reports CRLF:
sed -i 's/\r$//' skills/public/officecli/bin/officecli.sh
```

The binary itself must be transferred in binary mode (WinSCP binary, `scp`,
USB, NFS). Do not open or edit it.

## 3. How the file reaches the sandbox

Production path mapping:

| Stage | Path |
| --- | --- |
| Host checkout | `$REPO/skills/public/officecli` |
| Gateway container | `/app/skills/public/officecli` (bind mount, read-only) |
| Projection (host) | `$DEER_FLOW_HOME/skills_view/public/officecli` |
| Projection (Gateway) | `/app/backend/.deer-flow/skills_view/public/officecli` |
| Sandbox | `/mnt/skills/public/officecli` |

`$DEER_FLOW_HOME` is the host runtime directory (default
`$REPO/backend/.deer-flow`), mounted at `/app/backend/.deer-flow`. The
provisioner mounts the projection into each sandbox; it does not generate the
projection itself.

The projection is rebuilt when the public skills source signature changes.
Adding a new skill directory and binary changes that signature. The rebuild
happens at Gateway boot or on the next sandbox acquire. To make it deterministic
and immediate, restart the Gateway when the system is idle:

```bash
docker restart deer-flow-gateway
```

If you do not want to restart, start a new conversation/sandbox; the next
acquire should rebuild the projection. If the skill does not appear, restart the
Gateway. The provisioner does **not** need a restart. `POST /api/skills/reload`
(admin, process-local) is available in some builds as an alternative; it is not
a substitute for the source signature rebuild.

Verify on the host:

```bash
ls -l "$DEER_FLOW_HOME/skills_view/public/officecli/bin/officecli"
sha256sum "$DEER_FLOW_HOME/skills_view/public/officecli/bin/officecli"
```

If the projection is a hardlink, the checksum matches the source. If it is
missing, the rebuild has not run; check the Gateway logs and restart it.

## 4. Enable the skill and disable the image-only path

The production compose mounts `extensions_config.json` read-only, so edit the
**host** file; a direct admin API write may fail with a read-only filesystem.
The file is at `$DEER_FLOW_EXTENSIONS_CONFIG_PATH` (default
`$REPO/extensions_config.json`).

Merge these keys into the existing `"skills"` object; do not replace
`mcpServers` or other skills:

```json
{
  "skills": {
    "officecli": { "enabled": true },
    "ppt-generation": { "enabled": false },
    "office-documents": { "enabled": false }
  }
}
```

Why:

- `officecli`: the new offline Word/Excel/PowerPoint path. Public skills default
  to enabled; the explicit entry documents the intent.
- `ppt-generation`: image-only and depends on the cloud `image-generation`
  skill. It cannot run in the intranet and will compete for PPT triggers.
- `office-documents`: only if that skill directory is present in the target
  checkout; adding a config entry does not create the skill. It is not deployed
  today, but the entry prevents accidental overlap if the repo is updated.

A production file with `"skills": {}` does **not** mean "no skills". It means
there are no per-skill overrides, and public/custom/legacy skills default to
enabled (`ExtensionsConfig.is_skill_enabled`). In particular, `ppt-generation`
is enabled until it is explicitly disabled with `{"enabled": false}`.

After editing, restart the Gateway:

```bash
docker restart deer-flow-gateway
```

Confirm the three states in the admin UI/API. If your compose does not mount
the config read-only, the admin API (`PUT /api/skills/<name>` with
`{"enabled": false}`) can apply the same change and rebuild the projection
without a restart; follow your deployment's auth rules.

## 5. Sandbox smoke test

Start a new conversation (or `kubectl exec` into a new sandbox Pod) and run:

```bash
ls -l /mnt/skills/public/officecli/bin/
sh /mnt/skills/public/officecli/bin/officecli.sh --version
# expected: 1.0.157

OUT=/mnt/user-data/workspace/ocli-smoke.docx
rm -f "$OUT"
sh /mnt/skills/public/officecli/bin/officecli.sh create "$OUT" --locale zh-CN
sh /mnt/skills/public/officecli/bin/officecli.sh validate "$OUT"
sh /mnt/skills/public/officecli/bin/officecli.sh view "$OUT" outline
```

For a Unicode round-trip, use a UTF-8 JSON batch:

```bash
cat > /mnt/user-data/workspace/ocli-smoke.json <<'JSON'
[
  {"command":"add","parent":"/body","type":"paragraph","props":{"text":"中文冒烟测试","font":"微软雅黑","size":"11pt"}}
]
JSON
sh /mnt/skills/public/officecli/bin/officecli.sh batch "$OUT" \
  --input /mnt/user-data/workspace/ocli-smoke.json --json
sh /mnt/skills/public/officecli/bin/officecli.sh view "$OUT" text --max-lines 10
```

Expected: `Validation passed`, a paragraph outline, and the Chinese text intact.

### Common smoke-test failures

| Symptom | Meaning / action |
| --- | --- |
| `binary missing ... /mnt/skills/public/officecli/bin/officecli` | Source or projection is incomplete. Verify the host source, then rebuild/restart the Gateway. |
| `GLIBC_... not found` | Wrong binary/libc. Use the glibc x64 build; do not install libraries into the sandbox. |
| `Permission denied` on execute | The cache directory is on a noexec mount. Set `OFFICECLI_CACHE_DIR` to a writable executable directory and retry once, e.g. under `/mnt/user-data/workspace/.officecli-cache`. If that is also noexec, use `/root/.cache/officecli-bin`. |
| `sha256sum is required` | The sandbox image lacks coreutils `sha256sum`; this image should have it. Report the image/tag rather than bypassing the check. |
| `checksum mismatch` | The binary transfer was truncated or the wrong build was copied. Re-copy in binary mode and verify the SHA-256 on the host. |
| `create` says the file exists | Use a new path or `rm -f` first; the skill does this. |
| `view screenshot` fails | No browser/Playwright. This is expected; the skill falls back to `view html`/`view svg`. Do not add a browser just for preview. |

## 6. Updating the binary

1. Download the new Linux x64 release and verify its checksum.
2. Update `VERSION` and `EXPECTED_SHA256` in `bin/officecli.sh` (the cache key
   includes `VERSION`, so a version bump forces a fresh copy).
3. Replace `bin/officecli` on the host, restart the Gateway when idle, and run
   the smoke test in a new sandbox.
4. Keep `LICENSE`, `NOTICE`, and `THIRD-PARTY-NOTICES.txt` in sync with the
   upstream release.

Never run `officecli install`, `officecli plugins`, `officecli mcp`,
`officecli skills`, or `officecli watch` in production. Those paths fetch or
modify code/config and are outside this deployment's trust model.

## 7. Rollback

1. Set `"officecli": { "enabled": false }` in `extensions_config.json` and
   restart the Gateway.
2. Optionally remove the `skills/public/officecli` directory and the projection.
3. Re-enable `ppt-generation` only if a reachable image-generation service is
   available; otherwise keep it disabled.

The old `office-documents` skill and its tests remain in the repo; do not delete
them without an explicit decision.

## 8. Verified test record

Local QA on Windows with the matching v1.0.157 binary:

- PPTX: create + batch + validate + view; 2 slides, 5 shapes, 0 issues;
  Unicode text found in the OOXML package; screenshot rendered at 1280×720.
- DOCX: create + batch + validate; 5 paragraphs, 1 table, validation passed;
  `view issues` reported 4 advisory typography findings (3 missing first-line
  indents and 1 mixed CJK/Latin punctuation). `firstLineChars=200` removed the
  indent finding.
- XLSX: create + batch + validate; formula `AVERAGE(B2:B3)` displayed as
  `97.9%`; 0 issues, 0 error cells; Unicode text intact.
- Format-preserving replacement: `set --find/--replace` preserved paragraph/run
  fonts; the same `find`/`replace` pair works inside a batch item.
- Contrast: a dark slide background with the default title produced black text
  on navy; setting the title color explicitly fixed it. The skill documents
  this.
- `create --locale zh-CN` was accepted; it sets locale defaults but does not
  replace explicit element fonts (DOCX defaults remained 等线 / Times New
  Roman). The skill still requires explicit fonts for body text and table cells.
- `view html` prints the full HTML to stdout (redirect it to a file).
- `@phType=title` is rejected by v1.0.157 despite the help text; use
  `/slide[N]/shape[1]` or the `@id` path from `get`.
- Embedded `load_skill` guides are 35–45 KB; the skill instructs the agent not
  to load them by default.

The Linux binary was checksum- and file-type-verified locally but could not be
executed on the Windows development machine (no Docker/WSL). **Run the sandbox
smoke test in §5 before relying on it in production.**

## 9. Security and operational notes

- The binary executes with the sandbox's privileges, like any other skill
  command. Pin it by SHA-256 and only source it from the official release.
- The wrapper sets `OFFICECLI_SKIP_UPDATE=1` and disables .NET telemetry. It
  makes no network calls for the supported workflows.
- Avoid remote-asset features (KaTeX/LaTeX, Mermaid, 3D, remote images); the
  intranet has no route to those asset hosts.
- The skill has no access to company templates in the repo. Use user-uploaded
  templates; do not bundle branded templates into this public repository.
- `view screenshot` needs a browser. The sandbox may not have one; do not
  weaken the image or add Playwright just for preview. `view svg` (PPTX) and
  `view html` are structural fallbacks, not pixel-perfect proof.
- The skill deliberately avoids loading the embedded 35–45 KB design guides by
  default to protect the small model context window. Use `help` for property
  names.
- Macro-enabled, password-protected, and legacy `.doc/.xls/.ppt` files are not
  supported; PDF export is not available offline.

## Attribution

- OfficeCLI: <https://github.com/iOfficeAI/OfficeCLI> (Apache-2.0).
- The `SKILL.md` is adapted from the upstream OfficeCLI skill documentation.
  The vendored binary is unmodified v1.0.157.
- Upstream license and notice files are retained in this directory.
