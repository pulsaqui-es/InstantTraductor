"""Comprobación rápida de la cadena: un clip por condición con el texto emitido y las cifras clave."""

from __future__ import annotations

import sys
import time

from chain import ChainConfig, ChainRunner
from evalcore import clip_metrics, load_manifest
from common import C2_DIR, read_wav


def main() -> None:
    uid = sys.argv[1] if len(sys.argv) > 1 else "fx00"
    manifest = [m for m in load_manifest() if m["uid"] == uid]
    runner = ChainRunner(persist_cache=False)
    cfg = ChainConfig()
    for item in manifest:
        samples = read_wav(C2_DIR / item["clip"])
        t = time.perf_counter()
        r = clip_metrics(runner, item, cfg, samples, deep=True)
        print(
            f"{item['cond']:<10} rec={r['recall']:.2f} ideal={r['recall_ideal']:.2f} agc={r['recall_agc']:.2f} "
            f"vad={r['recall_vad']:.2f} lvl_in={r['speech_level_in_dbfs']:.0f} lvl_agc={r['speech_level_after_agc_dbfs']:.0f} "
            f"g0={r['gain_at_start_db']:.0f} pmax={r['vad_pmax_in_speech']:.2f} ov={r['vad_overlap_frac']:.2f} "
            f"units={r['n_units']} delay={r['delay_end_s']} t={time.perf_counter() - t:.1f}s"
        )
        print("    ref :", item["ref"][:90])
        print("    hyp :", r["text"][:90])


if __name__ == "__main__":
    main()
