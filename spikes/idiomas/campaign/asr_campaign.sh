#!/usr/bin/env bash
# Campaña de ASR del spike S5: tres colas (una por idioma) en paralelo.
# Desde spikes/idiomas:  bash campaign/asr_campaign.sh
# Los registros van fuera del repo: %LOCALAPPDATA%/InstantTraductor/spikes/idiomas/logs
cd "${BASH_SOURCE%/*}/.." || exit 1
LOGS="${LOCALAPPDATA}/InstantTraductor/spikes/idiomas/logs"
mkdir -p "$LOGS"
run() { uv run python run_asr.py "$@"; }
( for m in parakeet_ja reazon_ja sensevoice nemotron35 nemotron35_bp1; do run --model $m --lang ja; done ) > "$LOGS/asr_ja.log" 2>&1 &
( for m in xasr480 zipformer_zh sensevoice xasr960; do run --model $m --lang zh; done ) > "$LOGS/asr_zh.log" 2>&1 &
( for m in nemotron35 kangkyu32 sensevoice kangkyu64 nemotron35_bp1; do run --model $m --lang ko; done ) > "$LOGS/asr_ko.log" 2>&1 &
wait
