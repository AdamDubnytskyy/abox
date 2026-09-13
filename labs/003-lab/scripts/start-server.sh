#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LLAMA_BIN_DIR="$SCRIPT_DIR/../../../llms/llama.cpp/build/bin"
LOG=/tmp/setup.log

MAX_SLOT_CONTEXT_SIZE=8192
LOGICAL_MAX_BATCH_SIZE=512
PHYSICAL_MAX_BATCH_SIZE=512
USER="nomic-ai"
MODEL="nomic-embed-text-v1.5-GGUF:Q4_K_M"
MODEL_REPOSITORY=$USER/$MODEL

export LD_LIBRARY_PATH="$LLAMA_BIN_DIR:${LD_LIBRARY_PATH:-}"

exec > >(tee -a "$LOG") 2>&1

log() { echo "[$(date '+%H:%M:%S')] $*"; }

log "=== agentic-sandbox setup start ==="

echo $LLAMA_BIN_DIR

"$LLAMA_BIN_DIR/llama-server" \
  -hf $MODEL_REPOSITORY \
  --embedding \
  --pooling mean \
  -c $MAX_SLOT_CONTEXT_SIZE \
  -b $LOGICAL_MAX_BATCH_SIZE \
  -ub $PHYSICAL_MAX_BATCH_SIZE