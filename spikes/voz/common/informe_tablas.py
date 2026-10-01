"""Imprime en Markdown las tablas de resultados a partir de los JSON de spikes/voz/resultados/ (para el README).

    cd spikes/voz
    uv run python common/informe_tablas.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RES = Path(__file__).resolve().parents[1] / "resultados"


def cargar(nombre: str):
    p = RES / nombre
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def ms(x):
    return f"{x * 1000:.0f}"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    a = cargar("qwen3_completa_icl.json")
    af = cargar("qwen3_fria_icl.json")
    ax = cargar("qwen3_completa_xvec.json")
    b = cargar("chatterbox_completa.json")
    bf = cargar("chatterbox_fria.json")

    if a:
        print("### A: Qwen3-TTS-0.6B Base + faster-qwen3-tts (ICL, referencia cacheada, calentado)")
        print("| chunk_size | audio/chunk | TTFA p50 (ms) | TTFA p95 (ms) | TTFA máx (ms) | RTF p50 | RTF p95 | xRT p50 |")
        print("|---|---|---|---|---|---|---|---|")
        for cs, r in a["barrido_chunk_size"].items():
            t, f, x = r["ttfa_s"], r["rtf"], r["xrt"]
            print(f"| {cs} | {int(cs) * 1000 / 12:.0f} ms | {ms(t['p50'])} | {ms(t['p95'])} | {ms(t['max'])} | {f['p50']:.3f} | {f['p95']:.3f} | {x['p50']:.2f} |")
        print(f"\nn = {a['barrido_chunk_size']['8']['n_peticiones']} peticiones por fila (20 frases x 3 repeticiones).")
        print(f"Carga del modelo {a['carga_modelo_s']} s; captura de CUDA graphs {a.get('calentamiento_capturar_grafos_s')} s; prompt de la referencia {a['preparar_referencia_s']} s.")
        v = a["vram_pico"]
        print(f"VRAM: torch max_allocated {v['torch_max_allocated_mib']:.0f} MiB, max_reserved {v['torch_max_reserved_mib']:.0f} MiB; NVML pico total {v['nvml_pico_total_mib']:.0f} MiB (línea base {a['vram_linea_base_mib']['nvml']:.0f} MiB, delta {v['nvml_pico_menos_linea_base_mib']:.0f} MiB); nvidia-smi {v['nvidia_smi_ahora_mib']:.0f} MiB.")
    if af:
        print(f"\nArranque en frío (sin calentar): 1ª petición TTFA {af['peticion_fria']['ttfa_s']} s (total {af['peticion_fria']['total_s']} s), 2ª TTFA {af['segunda_peticion']['ttfa_s']} s; carga {af['carga_modelo_s']} s.")
    if ax:
        print("\n### A (x-vector, sin ref_text)")
        for cs, r in ax["barrido_chunk_size"].items():
            t, f = r["ttfa_s"], r["rtf"]
            print(f"| {cs} | {ms(t['p50'])} | {ms(t['p95'])} | {f['p50']:.3f} |")

    if b:
        print("\n### B: Chatterbox es-ES (PyTorch eager, fp32)")
        s = b["stream_principal"]
        print(f"Streaming (config {s['config']}): TTFA p50 {ms(s['ttfa_s']['p50'])} ms, p95 {ms(s['ttfa_s']['p95'])} ms; RTF p50 {s['rtf']['p50']:.3f}, p95 {s['rtf']['p95']:.3f}; xRT {s['xrt']['p50']:.2f}")
        print("| config | 1er chunk (tokens+3) | TTFA p50 (ms) | TTFA p95 (ms) | máx (ms) |")
        print("|---|---|---|---|---|")
        for n, r in b["barrido_ttfa"].items():
            t = r["ttfa_s"]
            print(f"| {n} | {r['config']['first_chunk_tokens']}+3 | {ms(t['p50'])} | {ms(t['p95'])} | {ms(t['max'])} |")
        fc = b["frase_completa_sin_marca"]
        print(f"Frase completa (oficial): tiempo hasta el audio completo p50 {fc['tiempo_hasta_audio_completo_s']['p50']:.2f} s, p95 {fc['tiempo_hasta_audio_completo_s']['p95']:.2f} s; RTF p50 {fc['rtf']['p50']:.3f}, p95 {fc['rtf']['p95']:.3f}")
        c0 = b["stream_cfg_weight_0"]
        print(f"cfg_weight=0 (batch 1): TTFA p50 {ms(c0['ttfa_s']['p50'])} ms, p95 {ms(c0['ttfa_s']['p95'])} ms; RTF p50 {c0['rtf']['p50']:.3f}")
        d = b["desglose_primer_chunk"]
        print(f"Desglose del 1er chunk (p10): prefill {d['prefill_ms_mediana']:.0f} ms + {d['pasos_hasta_primer_chunk']} pasos T3 x {d['ms_por_paso_T3_mediana']:.1f} ms + S3Gen {d['s3gen_primer_chunk_ms_mediana']:.0f} ms = {d['ttfa_ms_mediana']:.0f} ms")
        print(f"Marca de agua PerTh: {b['marca_agua_perth']}")
        print(f"Carga {b['carga_modelo_s']} s; referencia {b['preparar_referencia_s']} s")
        v = b["vram_pico"]
        print(f"VRAM: torch max_allocated {v['torch_max_allocated_mib']:.0f} MiB, max_reserved {v['torch_max_reserved_mib']:.0f} MiB; NVML pico total {v['nvml_pico_total_mib']:.0f} MiB (línea base {b['vram_linea_base_mib']['nvml']:.0f} MiB, delta {v['nvml_pico_menos_linea_base_mib']:.0f} MiB)")
    if bf:
        print(f"Arranque en frío: 1ª petición TTFA {bf['peticion_fria']['ttfa_s']} s (total {bf['peticion_fria']['total_s']} s), 2ª TTFA {bf['segunda_peticion']['ttfa_s']} s")

    for nombre in ("chatterbox_optim.json", "chatterbox_optim_p10.json"):
        o = cargar(nombre)
        if o and "optimizaciones" in o:
            print(f"\n### B: optimizaciones baratas ({nombre})")
            print("| variante | TF32 | pasos CFM | ref. S3Gen | TTFA p50 (ms) | TTFA p95 (ms) | RTF p50 |")
            print("|---|---|---|---|---|---|---|")
            for n, r in o["optimizaciones"].items():
                print(f"| {n} | {r['tf32']} | {r['cfm'] or 10} | {r['prompt'] or 'completa'} | {ms(r['ttfa_s']['p50'])} | {ms(r['ttfa_s']['p95'])} | {r['rtf']['p50']:.3f} |")

    for nombre, clave in (("qwen3_velocidad_icl.json", "velocidad_instruct"), ("chatterbox_velocidad.json", "velocidad_controles_indirectos")):
        v = cargar(nombre)
        if v and clave in v:
            print(f"\n### Velocidad nativa ({nombre})")
            for n, r in v[clave].items():
                print(f"- {n}: velocidad efectiva mediana {r['velocidad_efectiva_mediana']}x (min {r['velocidad_efectiva_min']}, max {r['velocidad_efectiva_max']})" + (f"; TTFA p50 {ms(r['ttfa_s']['p50'])} ms" if "ttfa_s" in r else ""))

    for nombre in ("asr_A_qwen3.json", "asr_B_chatterbox.json"):
        r = cargar(nombre)
        if r:
            print(f"\nASR ida y vuelta {nombre}: WER medio {r['wer_medio'] * 100:.1f} %, máx {r['wer_max'] * 100:.1f} %")


if __name__ == "__main__":
    main()
