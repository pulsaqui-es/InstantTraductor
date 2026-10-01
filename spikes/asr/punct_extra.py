"""Extra: restauración de puntuación y mayúsculas sobre los textos finales de una ejecución.

Comprueba si un modelo de puntuación aparte (sherpa-onnx ``OnlinePunctuation``, CNN-BiLSTM en
inglés, Apache-2.0, CPU) suple la falta de puntos finales de Nemotron con ``blank_penalty`` bajo.
Toma los textos finales de ``results/<etiqueta>.json``, los pasa a minúsculas y sin puntuación (como
si el ASR no puntuara) y mide el tiempo por llamada y la puntuación resultante.

Uso (desde ``spikes/asr``; antes ``fetch_assets.py --punct``)::

    uv run python punct_extra.py sweep_a160_bp0_gapped_fast sweep_a160_bp1_gapped_fast
"""

from __future__ import annotations

import argparse
import json
import re
import time

import numpy as np

from asrspike import metrics, paths


def strip_to_raw(text: str) -> str:
    """Minúsculas y sin puntuación (se conservan los apóstrofos)."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s']", " ", text.lower())).strip()


def profile(texts: list[str]) -> dict:
    prof = [metrics.punctuation_profile(t) for t in texts]
    words = sum(p["words"] for p in prof) or 1
    return {
        "comas/100 pal.": round(100 * sum(p["commas"] for p in prof) / words, 1),
        "marcas finales/100 pal.": round(100 * sum(p["terminal_marks"] for p in prof) / words, 1),
        "finales con . ? ! (%)": round(100 * sum(p["ends_with_terminal"] for p in prof) / max(len(prof), 1)),
        "palabras en mayúscula/100 pal.": round(100 * sum(p["capitalized_words"] for p in prof) / words, 1),
        "empiezan en mayúscula (%)": round(100 * sum(1 for t in texts if t[:1].isupper()) / max(len(texts), 1)),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("labels", nargs="+", help="etiquetas de results/*.json (motor A o B)")
    ap.add_argument("--save", default=None, help="guarda el resumen en este JSON (dentro de results/)")
    args = ap.parse_args()

    import sherpa_onnx

    base = paths.punct_dir()
    model_cfg = sherpa_onnx.OnlinePunctuationModelConfig(
        cnn_bilstm=str(base / "model.onnx"), bpe_vocab=str(base / "bpe.vocab"), num_threads=1
    )
    punct = sherpa_onnx.OnlinePunctuation(sherpa_onnx.OnlinePunctuationConfig(model_config=model_cfg))
    punct.add_punctuation_with_case("warm up the model")

    summary = {}
    for label in args.labels:
        res = json.loads((paths.RESULTS_DIR / f"{label}.json").read_text(encoding="utf-8"))
        texts = [r["text"] for r in res["result"]["segments"]]
        raw = [strip_to_raw(t) for t in texts]
        times, out = [], []
        for t in raw:
            c0 = time.perf_counter()
            out.append(punct.add_punctuation_with_case(t))
            times.append((time.perf_counter() - c0) * 1000)
        same = sum(metrics.normalize_en(a) == metrics.normalize_en(b) for a, b in zip(texts, out, strict=True))
        summary[label] = {
            "segmentos": len(texts),
            "ms_por_llamada": metrics.pct(times),
            "texto_normalizado_igual": f"{same}/{len(texts)}",
            "original": profile(texts),
            "con_modelo_de_puntuacion": profile(out),
            "ejemplos": [{"original": a, "restaurado": b} for a, b in list(zip(texts, out, strict=True))[:4]],
        }
        print(f"== {label} ==")
        print(f"  {len(texts)} segmentos; {np.median(times):.1f} ms por llamada (p50), {max(times):.1f} ms (máx.); texto normalizado igual en {same}/{len(texts)}")
        print("  original  :", summary[label]["original"])
        print("  restaurado:", summary[label]["con_modelo_de_puntuacion"])
        for ex in summary[label]["ejemplos"][:3]:
            print("   -", ex["original"], "\n     =>", ex["restaurado"])
    if args.save:
        (paths.RESULTS_DIR / args.save).write_text(json.dumps(summary, indent=1, ensure_ascii=False, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
