#!/bin/bash
# Campaña de ejecuciones a ritmo de tiempo real del spike S3 (la que produjo results/*_paced*.json).
# Se lanza desde Git Bash:  BP=1 bash campaign/paced_runs.sh > paced.log 2>&1
# Una ejecución detrás de otra para no pisarse; ~1 h 40 min en total.
cd "$(dirname "$0")/.." || exit 1
BP=${BP:-1}

quiet() { uv run python -W ignore campaign/wait_quiet.py 4 25 2>&1; }
runa() { echo; echo "######## A: $*"; quiet; uv run python -W ignore run_engine_a.py --save-events "$@" 2>&1; }
runb() { echo; echo "######## B: $*"; quiet; uv run python -W ignore run_engine_b.py --save-events "$@" 2>&1; }

# 1) Motor A, flujo con huecos (frases sueltas), ~10 min cada uno
runa --stream gapped --chunk-ms 160 --mode paced --threads 2 --blank-penalty $BP --label a160_vad_gapped_paced
runa --stream gapped --chunk-ms 560 --mode paced --threads 2 --blank-penalty $BP --label a560_vad_gapped_paced
# 2) Motor B (un solo candado de GPU para las dos): con huecos (~10 min) y habla continua (~3 min)
runb --variant b_gapped_paced:gapped:paced:1:5 --variant b_continuous_paced:continuous:paced:1:5
# 3) Motor A, habla continua (>= 3 min)
runa --stream continuous --chunk-ms 160 --mode paced --threads 2 --blank-penalty $BP --label a160_vad_continuous_paced
runa --stream continuous --chunk-ms 560 --mode paced --threads 2 --blank-penalty $BP --label a560_vad_continuous_paced
# 4) Sin VAD: endpoint nativo de sherpa-onnx
runa --stream gapped --chunk-ms 160 --policy native --mode paced --threads 2 --blank-penalty $BP --label a160_native_gapped_paced
# 5) Hilos (habla continua = peor caso de CPU)
for th in 1 4; do
  runa --stream continuous --chunk-ms 160 --mode paced --threads $th --blank-penalty $BP --label a160_vad_continuous_paced_t$th
  runa --stream continuous --chunk-ms 560 --mode paced --threads $th --blank-penalty $BP --label a560_vad_continuous_paced_t$th
done
# 6) Silencio que cierra el turno: 300 ms
runa --stream gapped --chunk-ms 560 --mode paced --threads 2 --blank-penalty $BP --min-silence-ms 300 --label a560_vad_gapped_paced_minsil300
# 7) Tamaño del trozo de entrada (20 / 32 / 100 ms) sobre los 25 primeros enunciados
for dev in 20 32 100; do
  runa --stream gapped --chunk-ms 560 --mode paced --threads 2 --blank-penalty $BP --limit 25 --device-chunk-ms $dev --label a560_vad_gapped_paced_dev${dev}_lim25
done
echo "PACED TERMINADO"
