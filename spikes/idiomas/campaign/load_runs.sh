#!/usr/bin/env bash
# Candidatos principales con la CPU cargada por 12 procesos ocupados (75 % de los 16 hilos), uno detrás de otro.
# Desde spikes/idiomas:  bash campaign/load_runs.sh
cd "${BASH_SOURCE%/*}/.." || exit 1
LOGS="${LOCALAPPDATA}/InstantTraductor/spikes/idiomas/logs"
mkdir -p "$LOGS"
uv run python campaign/cpu_hog.py 12 1500 &
HOG=$!
sleep 5
for spec in "parakeet_ja ja" "reazon_ja ja" "xasr960 zh" "sensevoice zh" "sensevoice ko" "nemotron35_bp1 ko" "kangkyu64 ko"; do
  set -- $spec
  uv run python run_asr.py --model "$1" --lang "$2" --tag _carga
done > "$LOGS/asr_carga.log" 2>&1
kill $HOG 2>/dev/null
wait
