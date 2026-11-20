#!/usr/bin/env bash
# Install and verify Hangul-capable fonts for the unprivileged GUI Chromium.
set -Eeuo pipefail

mode="${1:-install}"
if [[ "$mode" != "install" && "$mode" != "--check" ]]; then
  echo "Usage: $0 [--check]" >&2
  exit 2
fi

if [[ "$mode" == "install" ]]; then
  if (( EUID != 0 )); then
    echo "Korean font installation requires root privileges" >&2
    exit 1
  fi
  # Noto provides comprehensive CJK coverage; Nanum provides Korean fallback.
  packages=(fontconfig fonts-noto-cjk fonts-nanum)
  missing=()
  for package in "${packages[@]}"; do
    status="$(dpkg-query -W -f='${Status}' "$package" 2>/dev/null || true)"
    if [[ "$status" != "install ok installed" ]]; then
      missing+=("$package")
    fi
  done
  if (( ${#missing[@]} )); then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y --no-install-recommends "${missing[@]}"
  fi
  # Refresh the system font cache before Chromium is (re)started.
  fc-cache -f >/dev/null
fi

for command in fc-list fc-match; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "[FAIL] $command is missing; install fontconfig" >&2
    exit 1
  fi
done

# Check font discovery as the service user, not only as root. The service's
# systemd ProtectHome setting does not hide /usr/share/fonts.
if id mcpstack >/dev/null 2>&1; then
  font_query=(runuser -u mcpstack --)
else
  font_query=()
fi

korean_fonts="$("${font_query[@]}" fc-list -f '%{family}\n' ':lang=ko')"
if [[ -z "$korean_fonts" ]]; then
  echo "[FAIL] Fontconfig cannot find a Hangul-capable font (:lang=ko)" >&2
  exit 1
fi
matched_family="$("${font_query[@]}" fc-match -f '%{family}\n' 'sans:lang=ko')"
if [[ -z "$matched_family" ]]; then
  echo "[FAIL] Fontconfig did not select a Korean fallback font" >&2
  exit 1
fi
echo "[PASS] GUI Chromium Korean fonts available: ${matched_family%%,*}"
