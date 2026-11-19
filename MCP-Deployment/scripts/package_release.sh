#!/usr/bin/env bash
# Build a versioned, credential-free source installer for Ubuntu/Debian.
set -Eeuo pipefail

version="$1"
commit="$2"
if [[ "$version" != "snapshot" && ! "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]]; then
  echo "Version must be vMAJOR.MINOR.PATCH (optionally -suffix)" >&2
  exit 1
fi
[[ "$commit" =~ ^[0-9a-f]{40}$ ]] || { echo "Invalid commit SHA" >&2; exit 1; }

root="$(cd "$(dirname "$0")/../.." && pwd)"
stage="$(mktemp -d)"
trap 'rm -rf -- "$stage"' EXIT
mkdir -p "$root/dist"

# Archive only deployment source, never generated runtime credentials or CI evidence.
tar -C "$root" \
  --exclude='MCP-Deployment/runtime' \
  --exclude='MCP-Deployment/evidence' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='*.pyo' \
  --exclude='*.pem' \
  --exclude='*.key' \
  --exclude='private.env' \
  -cf - MCP-Deployment | tar -C "$stage" -xf -

printf '%s\n' "$version" > "$stage/MCP-Deployment/VERSION"
printf '%s\n' "$commit" > "$stage/MCP-Deployment/COMMIT"
archive="$root/dist/mcp-deployment-$version.tar.gz"
tar -C "$stage" -czf "$archive" MCP-Deployment

if tar -tzf "$archive" | grep -E '(^|/)(runtime|evidence)/|\.pem$|\.key$|\.pyc$|private\.env$'; then
  echo "ERROR: release archive includes runtime data or a potentially sensitive file" >&2
  exit 1
fi

cp -- "$archive" "$root/dist/mcp-release.tar.gz"
(cd "$root/dist" && sha256sum "mcp-deployment-$version.tar.gz" > "mcp-deployment-$version.tar.gz.sha256")
echo "PACKAGE PASS version=$version commit=$commit"
ls -lh "$archive" "$archive.sha256"
