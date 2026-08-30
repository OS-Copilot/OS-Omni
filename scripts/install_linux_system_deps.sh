#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "This script only supports Linux." >&2
  exit 2
fi

if ! command -v apt-get >/dev/null 2>&1; then
  echo "apt-get not found. Please install dependencies manually for your distro." >&2
  exit 2
fi

SUDO=""
if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
  else
    echo "Please run as root or install sudo." >&2
    exit 2
  fi
fi

echo "Installing Linux system dependencies for OS-Omni..."

$SUDO apt-get update
$SUDO apt-get install -y \
  x11-xserver-utils \
  x11-apps \
  openbox \
  twm \
  gnome-terminal \
  xdotool \
  wmctrl \
  scrot \
  imagemagick \
  python3-pyatspi \
  libreoffice \
  python3-uno \
  xvfb

echo
echo "System package installation complete."
echo "Next steps:"
echo "  1) bash scripts/setup_env.sh"
echo "  2) source .venv/bin/activate"
echo "  3) python scripts/check_env.py --platform linux"

