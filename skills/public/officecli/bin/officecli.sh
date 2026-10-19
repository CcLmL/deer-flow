#!/bin/sh
# OfficeCLI launcher for the DeerFlow sandbox.
#
# The skill directory is mounted read-only and may be noexec, so copy the
# pinned Linux x64 binary into a writable cache and run it from there.
# See ../DEPLOY.md for checksums and deployment steps.

set -eu
umask 022

EXPECTED_SHA256="f8eefe88dbfa7464bee421e5421efe57fc26bc3180b30e56eef58594c8245c94"
VERSION="1.0.157"

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
src="$here/officecli"

if [ ! -f "$src" ]; then
    echo "officecli: binary missing at $src" >&2
    echo "officecli: deploy skills/public/officecli/bin/officecli; see skills/public/officecli/DEPLOY.md" >&2
    exit 127
fi
if [ ! -r "$src" ]; then
    echo "officecli: binary not readable at $src" >&2
    exit 126
fi

if [ -n "${OFFICECLI_CACHE_DIR:-}" ]; then
    cache_root="$OFFICECLI_CACHE_DIR"
    if ! mkdir -p "$cache_root" 2>/dev/null; then
        echo "officecli: cannot create OFFICECLI_CACHE_DIR=$cache_root" >&2
        exit 126
    fi
elif mkdir -p "${HOME:-/tmp}/.cache/officecli-bin" 2>/dev/null; then
    cache_root="${HOME:-/tmp}/.cache/officecli-bin"
else
    cache_root="${TMPDIR:-/tmp}/officecli-bin"
    mkdir -p "$cache_root"
fi

dst="$cache_root/officecli-$VERSION"
src_size=$(wc -c < "$src" | tr -d ' ')
dst_size=""
if [ -f "$dst" ]; then
    dst_size=$(wc -c < "$dst" | tr -d ' ')
fi

if [ ! -f "$dst" ] || [ "$dst_size" != "$src_size" ]; then
    command -v sha256sum >/dev/null 2>&1 || {
        echo "officecli: sha256sum is required to verify the binary" >&2
        exit 126
    }
    actual=$(sha256sum "$src" | cut -d' ' -f1)
    if [ "$actual" != "$EXPECTED_SHA256" ]; then
        echo "officecli: checksum mismatch for $src" >&2
        echo "officecli: expected $EXPECTED_SHA256" >&2
        echo "officecli: actual   $actual" >&2
        exit 126
    fi
    tmp="$dst.$$"
    cp "$src" "$tmp"
    chmod 0755 "$tmp"
    mv -f "$tmp" "$dst"
fi

dotnet_dir="$cache_root/dotnet"
mkdir -p "$dotnet_dir"

exec env \
    OFFICECLI_SKIP_UPDATE=1 \
    OFFICECLI_NO_AUTO_RESIDENT=1 \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    DOTNET_NOLOGO=1 \
    DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1 \
    DOTNET_BUNDLE_EXTRACT_BASE_DIR="$dotnet_dir" \
    "$dst" "$@"
