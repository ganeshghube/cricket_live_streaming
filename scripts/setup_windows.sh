#!/bin/bash
# SportsCaster Pro v2 - Windows Dev Setup (Git Bash)
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "============================================"
echo "  SportsCaster Pro v2 - Windows Setup"
echo "  Project: ${SCRIPT_DIR}"
echo "============================================"

# Check Python
echo "[1/4] Checking Python..."
PYTHON="python"
command -v python &>/dev/null || PYTHON="python3"
command -v $PYTHON &>/dev/null || { echo "ERROR: Python not found"; exit 1; }
$PYTHON --version

# Check FFmpeg
echo "[2/4] Checking FFmpeg..."
command -v ffmpeg &>/dev/null && ffmpeg -version 2>&1 | head -1 || \
  echo "WARNING: FFmpeg not found. Download from https://ffmpeg.org/download.html"

# Create venv
echo "[3/4] Creating virtual environment..."
cd "${SCRIPT_DIR}"
$PYTHON -m venv venv

# Resolve venv Python
VENV_PY=""
for c in "venv/Scripts/python.exe" "venv/Scripts/python" "venv/bin/python3" "venv/bin/python"; do
  [ -f "$c" ] && { VENV_PY="$c"; break; }
done
[ -z "$VENV_PY" ] && { echo "ERROR: venv Python not found"; exit 1; }
echo "  Venv Python: ${VENV_PY}"

# Install packages
echo "[4/4] Installing packages..."
"${VENV_PY}" -m pip install --upgrade pip wheel --quiet
"${VENV_PY}" -m pip install \
  fastapi==0.111.0 \
  "uvicorn[standard]==0.30.1" \
  websockets==12.0 \
  pydantic==2.7.1 \
  "pydantic-settings==2.3.1" \
  opencv-python==4.9.0.80 \
  numpy==1.26.4 \
  python-multipart==0.0.9

mkdir -p recordings reviews models training_data config

echo ""
echo "============================================"
echo "  Setup complete!"
echo "  Start with:"
echo "    ${VENV_PY} run.py"
echo "  Then open: http://localhost:3000"
echo "  Login: admin / admin"
echo "============================================"
