"""Mide en CPU el indicio de acento (Δ s−θ) de las tomas de `sondear_acento.py`, agrupadas por variante de descripción.

    uv run --project spikes/voces python spikes/voces/evaluar_sonda.py            # carpeta _trabajo/sonda (Qwen3-VoiceDesign)
    uv run --project spikes/voces python spikes/voces/evaluar_sonda.py sonda_vox  # carpeta _trabajo/sonda_vox (VoxCPM2)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402


def main() -> None:
    dst = c.work_dir(sys.argv[1] if len(sys.argv) > 1 else "sonda")
    log = c.leer_json(dst / "sonda_log.json")
    por_var: dict[str, list] = {}
    for e in log:
        a, sr = c.vb.read_wav_mono(dst / e["fichero"])
        asr = c.transcribir(a, sr)
        tk = c.acento_tokens(a, sr, asr["chunks"])
        st = c.f0_stats(a, sr)
        ac = c.acento_resumen(tk)
        w = c.wer(e["texto"], asr["text"])
        por_var.setdefault(e["variante"], []).append(tk)
        print(f"{e['fichero']:28s} dur {len(a) / sr:4.1f} s | WER {w:.2f} | F0 {st.get('f0_mediana_hz')} Hz | n_θ={ac['n_theta']} n_s={ac['n_s']} Δ={ac['delta_s_menos_theta_db']} | {asr['text'][:90]}")
    print()
    resumen = {}
    for v, tks in por_var.items():
        ac = c.acento_resumen(c.juntar_tokens(tks))
        resumen[v] = ac
        print(f"{v:12s} agrupado: n_θ={ac['n_theta']:2d} n_s={ac['n_s']:2d} Δ(s−θ)={ac['delta_s_menos_theta_db']} dB  p={ac['p_mann_whitney']}")
    c.guardar_json(dst / "sonda_resumen.json", resumen)


if __name__ == "__main__":
    main()
