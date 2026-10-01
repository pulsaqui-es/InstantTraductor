"""Imprime en Markdown la tabla de candidatas del README a partir de `medidas.json` y de los `<id>_ref.json` (sin teclear cifras a mano).

    uv run --project spikes/voces python spikes/voces/tabla_readme.py            # tabla de candidatas (medidas de lo generado)
    uv run --project spikes/voces python spikes/voces/tabla_readme.py --refs     # tabla de referencias (ref_text, duración, origen)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402
import disenos as d  # noqa: E402

CAMINO = {"dis": "A (diseñada)", "est": "B (estudio)", "ctrl": "control (LibriVox)"}


def descripcion(cid: str, ref: dict) -> str:
    base = cid.split("-xv")[0].split("-rth")[0]
    m = base.replace("th", "") if base.startswith("es-f-dis") and base.endswith("th") else base
    for v in d.DISENOS:
        if v["id"] == m:
            extra = " + «th» en el texto de la referencia" if base.endswith("th") else ""
            return f"{v['nombre']}: {v['timbre']}; origen pedido: {v['lugar']}{extra}"
    return ref.get("name", cid)


def licencia(ref: dict) -> str:
    lic = ref.get("license", "")
    if lic.startswith("CC0"):
        return "CC0 (VoxPopuli); audio © Parlamento Europeo, cita la fuente"
    if lic.startswith("CC BY-SA"):
        return "CC BY-SA 4.0 (OpenSLR SLR61, © Google)"
    if lic.startswith("Apache"):
        return "Apache-2.0 (modelo VoiceDesign); sin voz humana"
    return lic[:60]


def tabla_refs() -> None:
    out = c.out_dir()
    print("| id | duración | F0 mediana | ref_text (exacto) | origen |")
    print("|---|---|---|---|---|")
    for p in sorted(out.glob("*_ref.json")):
        r = c.leer_json(p)
        origen = r.get("source", "")
        if r["voice_id"].startswith("es-f-dis"):
            origen = f"Qwen3-TTS-1.7B-VoiceDesign, toma `{r.get('fichero_origen', '')}`, semilla {r.get('semilla')}"
        elif r["voice_id"].startswith("es-f-est"):
            origen = f"{r.get('source', '')[:90]}; hablante {r.get('speaker_id')}"
        print(f"| `{r['voice_id']}` | {r.get('duracion_s', '')} s | {r.get('f0_mediana_hz', '')} Hz | «{r['ref_text']}» | {origen} |")


def main() -> None:
    if "--refs" in sys.argv:
        return tabla_refs()
    out = c.out_dir()
    med = c.leer_json(out / "medidas.json")
    filas = []
    for cid, m in sorted(med.items()):
        base = cid.split("-xv")[0].split("-rth")[0]
        refp = out / f"{base}_ref.json"
        ref = c.leer_json(refp) if refp.exists() else {}
        tipo = base.split("-")[2]
        ac = m["acento"]
        p = ac["p_mann_whitney"]
        f0 = f"{m['f0_mediana_hz']:.0f} Hz / {m['f0_rango_st_medio']:.1f} st"
        obs = []
        if m["frases_rotas"]:
            obs.append("frases rotas: " + ",".join(map(str, m["frases_rotas"])))
        obs.append(f"WER medio {m['wer_medio']:.2f}")
        filas.append(f"| `{cid}` | {CAMINO.get(tipo, tipo)} | {descripcion(cid, ref)} | {licencia(ref)} | "
                     f"**{ac['delta_s_menos_theta_db']}** dB (n {ac['n_theta']}/{ac['n_s']}{'' if p is None else f', p={p:.3f}'}) | {f0} | {m['duracion_total_s']:.0f} s | {'; '.join(obs)} |")
    print("| id | camino | descripción | licencia | indicio de acento Δ(s−θ) | F0 mediana / rango p10–p90 | duración 4 frases | observaciones |")
    print("|---|---|---|---|---|---|---|---|")
    print("\n".join(filas))


if __name__ == "__main__":
    main()
