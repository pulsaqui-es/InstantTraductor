"""Monta los dos flujos de prueba a partir de LibriSpeech dummy (fuera del repo).

- ``gapped``: los 73 enunciados separados por huecos de ruido muy bajo (frases sueltas).
- ``continuous``: enunciados pegados sin hueco, al menos 180 s de habla continua.

Uso (desde ``spikes/asr``)::

    uv run python build_corpus.py
"""

from __future__ import annotations

import argparse

from asrspike import data, paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--continuous-min-s", type=float, default=180.0)
    args = parser.parse_args()

    utts = data.load_utterances()
    total = sum(u.duration for u in utts)
    print(f"{len(utts)} enunciados, {total:.1f} s de habla, {sum(len(u.text.split()) for u in utts)} palabras")

    out = paths.corpus_dir()
    for plan in (
        data.build_gapped(utts, gap_range=(1.2, 1.8)),
        data.build_continuous(utts, min_duration_s=args.continuous_min_s),
    ):
        plan.save(out)
        words = sum(len(u["text"].split()) for u in plan.utterances)
        print(
            f"- {plan.name}: {plan.duration:.1f} s, {len(plan.utterances)} enunciados, {words} palabras, "
            f"{len(plan.oracle_intervals)} intervalos de habla (oráculo) -> {out / (plan.name + '.wav')}"
        )


if __name__ == "__main__":
    main()
