#!/bin/bash
# Barrido de blank_penalty (modo rápido, flujo con huecos completo; solo WER y puntuación).
# Se lanza desde Git Bash:  bash campaign/bp_sweep.sh > sweep.log 2>&1   (~35 min)
cd "$(dirname "$0")/.." || exit 1
for ms in 560 160; do
  for bp in 0 1 2 3; do
    echo "######## chunk=$ms blank_penalty=$bp"
    uv run python -W ignore run_engine_a.py --stream gapped --chunk-ms $ms --mode fast --threads 4 \
      --blank-penalty $bp --label "sweep_a${ms}_bp${bp}_gapped_fast" 2>&1 | grep -v "^  mayor consumo"
  done
done
echo "SWEEP TERMINADO"
