#!/bin/sh
# arccode uninstaller - curl -fsSL https://acnologiaslayer.github.io/arccode/uninstall.sh | sh
set -eu
ARCCODE_HOME="${ARCCODE_HOME:-$HOME/.arccode}"
VENV_DIR="$ARCCODE_HOME/venv"
LINK="$HOME/.local/bin/arccode"
removed=0

# 1. pipx-managed install
if command -v pipx >/dev/null 2>&1 && pipx list 2>/dev/null | grep -q arccode; then
  echo "==> removing via pipx"
  pipx uninstall arccode && removed=1
fi

# 2. isolated venv (the installer's default) + symlink
if [ -d "$VENV_DIR" ]; then
  echo "==> removing venv at $VENV_DIR"
  rm -rf "$VENV_DIR" && removed=1
fi
if [ -L "$LINK" ] || [ -f "$LINK" ]; then
  echo "==> removing $LINK"
  rm -f "$LINK" && removed=1
fi

# 3. pip --user install
if [ "$removed" -eq 0 ]; then
  for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then
      "$cand" -m pip uninstall -y arccode 2>/dev/null && removed=1 && break
    fi
  done
fi

if [ "$removed" -eq 1 ]; then
  echo "arccode removed. Config remains at $ARCCODE_HOME (delete manually if desired)."
else
  echo "arccode did not appear to be installed."
fi
