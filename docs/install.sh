#!/bin/sh
# arccode installer - curl -fsSL https://acnologiaslayer.github.io/arccode/install.sh | sh
#
# Installs the arccode CLI. Prefers pipx (isolated), falls back to an isolated venv.
# By default installs the latest release from PyPI. Env overrides:
#   ARCCODE_SOURCE=pypi|git    install source (default: pypi)
#   ARCCODE_REF=<git ref>      with ARCCODE_SOURCE=git, a branch/tag (default: master)
#   ARCCODE_METHOD=pipx|venv|pip   force an install method
set -eu

REPO="acnologiaslayer/arccode"
SOURCE="${ARCCODE_SOURCE:-pypi}"
REF="${ARCCODE_REF:-master}"
if [ "$SOURCE" = "git" ]; then
  SPEC="git+https://github.com/${REPO}@${REF}"
else
  SPEC="arccode"
fi

# ---- pretty output ----
if [ -t 1 ]; then
  B="$(printf '\033[1m')"; G="$(printf '\033[32m')"; Y="$(printf '\033[33m')"
  R="$(printf '\033[31m')"; C="$(printf '\033[36m')"; N="$(printf '\033[0m')"
else
  B=""; G=""; Y=""; R=""; C=""; N=""
fi
info() { printf "%s\n" "${C}==>${N} $*"; }
warn() { printf "%s\n" "${Y}warning:${N} $*" >&2; }
err()  { printf "%s\n" "${R}error:${N} $*" >&2; exit 1; }

printf "%s\n" "${B}arccode installer${N}"

# ---- find a python >= 3.10 ----
PY=""
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1; then
    if "$cand" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,10) else 1)' 2>/dev/null; then
      PY="$cand"; break
    fi
  fi
done
[ -n "$PY" ] || err "Python 3.10+ is required but was not found. Install Python and re-run."
info "using $($PY --version 2>&1) at $(command -v "$PY")"

# ---- choose method ----
METHOD="${ARCCODE_METHOD:-}"
if [ -z "$METHOD" ]; then
  if command -v pipx >/dev/null 2>&1; then
    METHOD="pipx"
  else
    METHOD="venv"
  fi
fi

VENV_DIR="${ARCCODE_HOME:-$HOME/.arccode}/venv"
BIN_DIR="$HOME/.local/bin"

install_pipx() {
  info "installing with pipx (isolated)"
  if pipx install --force "$SPEC"; then
    return 0
  fi
  warn "pipx install failed; falling back to an isolated venv"
  METHOD="venv"; install_venv
}

install_venv() {
  info "installing into an isolated venv at $VENV_DIR"
  "$PY" -m venv "$VENV_DIR" 2>/dev/null || err "could not create venv (need python3-venv). On Debian/Ubuntu: sudo apt install python3-venv"
  "$VENV_DIR/bin/python" -m pip install --upgrade pip >/dev/null 2>&1 || true
  "$VENV_DIR/bin/pip" install --upgrade "$SPEC" || err "install into venv failed"
  mkdir -p "$BIN_DIR"
  ln -sf "$VENV_DIR/bin/arccode" "$BIN_DIR/arccode"
  info "linked $BIN_DIR/arccode -> $VENV_DIR/bin/arccode"
}

install_pip() {
  info "installing with pip --user"
  if ! "$PY" -m pip install --user --upgrade "$SPEC" 2>/dev/null; then
    warn "pip --user unavailable (PEP 668 externally-managed?); using an isolated venv"
    METHOD="venv"; install_venv
  fi
}

case "$METHOD" in
  pipx) install_pipx ;;
  venv) install_venv ;;
  pip)  install_pip ;;
  *)    err "unknown ARCCODE_METHOD=$METHOD (use pipx, venv, or pip)" ;;
esac

# ---- locate the installed binary + PATH hint ----
BIN=""
if command -v arccode >/dev/null 2>&1; then
  BIN="$(command -v arccode)"
else
  USER_BASE="$("$PY" -m site --user-base 2>/dev/null || echo "$HOME/.local")"
  for p in "$USER_BASE/bin/arccode" "$HOME/.local/bin/arccode"; do
    [ -x "$p" ] && BIN="$p" && break
  done
fi

printf "\n"
if [ -n "$BIN" ] && command -v arccode >/dev/null 2>&1; then
  info "${G}installed${N}: $BIN"
  arccode version 2>/dev/null || true
elif [ -n "$BIN" ]; then
  info "${G}installed${N}: $BIN"
  BIN_DIR="$(dirname "$BIN")"
  warn "$BIN_DIR is not on your PATH. Add it:"
  printf "    %s\n" "export PATH=\"$BIN_DIR:\$PATH\""
  printf "  then restart your shell, or run pipx ensurepath.\n"
else
  err "installation finished but the arccode binary was not found on PATH."
fi

printf "\n%s\n" "${B}Next steps${N}"
printf "  export ANTHROPIC_API_KEY=...   %s\n" "# or OPENAI_API_KEY, or run local with Ollama"
printf "  arccode run \"Summarize this repo\"\n"
printf "  arccode --help\n"
printf "\nDocs: https://github.com/%s\n" "$REPO"
