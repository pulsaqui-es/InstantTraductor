"""Sonda de acento del modelo VoiceDesign: ¿alguna formulación de la descripción logra distinguir /θ/ de /s/?

Se genera una frase densa en palabras con z/ce/ci y con s (la misma para todas las variantes) con la MISMA voz base y distintas
formas de pedir el acento; después `evaluar_sonda.py` mide el indicio (Δ s−θ) en CPU. Se ejecuta en el entorno de `spikes/voz/qwen3`,
bajo el candado de GPU:

    uv run --project spikes/voz/qwen3 python spikes/voces/sondear_acento.py --takes 2
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402

vb = c.vb

# Palabras con /θ/ (hace, cinco, Cecilia, decidió, cenar, pizza, plaza, cerró, cerveza) y con /s/ (sentó, se, sábado, sala, siempre).
TEXTO_SONDA = "Hace cinco días, Cecilia decidió cenar pizza en la plaza; luego cerró la sala, se sentó y pidió una cerveza, como siempre."

BASE = "Female, 25 years old, medium-pitched soft and warm voice, gentle and friendly, natural expressive intonation, clear diction, relaxed natural pace."

# Reescrituras del texto para forzar /θ/: «th» (la grafía inglesa) y «θ» (símbolo fonético). El ref_text de un uso real seguiría siendo el texto normal.
TEXTO_TH = "Hathe thinco días, Thethilia dethidió thenar pitha en la platha; luego therró la sala, se sentó y pidió una thervetha, como siempre."
TEXTO_THETA = "Haθe θinco días, Θeθilia deθidió θenar piθa en la plaθa; luego θerró la sala, se sentó y pidió una θerveθa, como siempre."

INSTRUCTS: dict[str, str] = {
    "base_en": BASE + " Native speaker of standard Castilian Spanish from Madrid, Spain, with the peninsular accent: she pronounces 'z' and 'c' before e/i as the voiceless dental 'th' sound, clearly different from 's'.",
    "fuerte_en": BASE + " Native of Spain, NOT Latin American: a strong Castilian accent with distinción. She always pronounces 'z' and 'ce'/'ci' as the interdental fricative /θ/ like the English 'th' in 'think' (cena sounds like 'thena', zapato like 'thapato'), and keeps the apical 's' for 's'. No seseo.",
    "doblaje_en": BASE + " She is a professional Spanish voice-over and dubbing actress from Spain (doblaje al castellano de España), with the neutral Castilian dubbing accent of Madrid: interdental 'th' for z/ce/ci, apical 's'.",
    "fuerte_es": "Mujer de 25 años, voz suave y cálida de tono medio, amable y cercana, entonación natural y expresiva, dicción clara, ritmo natural. Nacida en España, no latinoamericana: acento castellano peninsular marcado, con distinción: pronuncia la «z» y «ce»/«ci» con la zeta interdental /θ/ (como la «th» inglesa de «think») y la «s» apical, nunca seseo.",
    "doblaje_es": "Mujer de 25 años, voz suave y cálida de tono medio, entonación natural y expresiva, dicción clara. Actriz de doblaje y locutora profesional de España, con el acento castellano neutro del doblaje peninsular (Madrid): zeta interdental en z/ce/ci y s apical.",
    "lisp_en": BASE + " She has a Castilian lisp-like accent typical of Spain: 'z', 'ce' and 'ci' sound like a soft English 'th' (as in 'think'), unlike Latin American Spanish where they sound like 's'.",
    "sin_acento": BASE,
}

# nombre -> (instruct, texto)
VARIANTES: dict[str, tuple[str, str]] = {k: (v, TEXTO_SONDA) for k, v in INSTRUCTS.items()}
VARIANTES["base_en_th"] = (INSTRUCTS["base_en"], TEXTO_TH)
VARIANTES["fuerte_en_th"] = (INSTRUCTS["fuerte_en"], TEXTO_TH)
VARIANTES["base_en_theta"] = (INSTRUCTS["base_en"], TEXTO_THETA)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--takes", type=int, default=2)
    ap.add_argument("--variantes", default="", help="subconjunto separado por comas; vacío = todas")
    ap.add_argument("--modelo", default=str(vb.models_dir() / c.QWEN3_DESIGN_DIR))
    ap.add_argument("--semilla-base", type=int, default=777)
    args = ap.parse_args()

    nombres = [x for x in VARIANTES if not args.variantes or x in args.variantes.split(",")]
    dst = c.work_dir("sonda")
    log_p = dst / "sonda_log.json"
    log = json.loads(log_p.read_text(encoding="utf-8")) if log_p.exists() else []
    with vb.gpu_lock():
        import torch
        from faster_qwen3_tts import FasterQwen3TTS

        model = FasterQwen3TTS.from_pretrained(args.modelo, device="cuda", dtype=torch.bfloat16, attn_implementation="sdpa", max_seq_len=2048)
        for nombre in nombres:
            for k in range(args.takes):
                seed = args.semilla_base + k
                torch.manual_seed(seed)
                t0 = time.perf_counter()
                instr, texto = VARIANTES[nombre]
                audios, sr = model.generate_voice_design(text=texto, instruct=instr, language="Spanish", max_new_tokens=15 * 12)
                a = np.asarray(audios[0], dtype=np.float32).reshape(-1)
                fich = f"sonda_{nombre}_t{k + 1}.wav"
                vb.write_wav(dst / fich, a, sr)
                print(f"{fich}: {len(a) / sr:.1f} s en {time.perf_counter() - t0:.1f} s", flush=True)
                log.append({"fichero": fich, "variante": nombre, "toma": k + 1, "semilla": seed, "instruct": instr, "texto_enviado": texto, "texto": TEXTO_SONDA})
    log_p.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
