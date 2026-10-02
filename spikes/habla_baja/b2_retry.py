"""B2: posedición por reglas + reintento con el 7B solo para lo marcado, en línea (necesita GPU).

Por cada línea de B0, escena a escena (el contexto son las traducciones ya elegidas, saneadas):
  1. traduce con la variante de prompt (por defecto `base`, el prompt de producción);
  2. aplica la posedición por reglas (`postedit`);
  3. marca para reintento si, tras la posedición:
       - queda «ustedes» (ust_left), o
       - el inglés lleva una marca de plural («you guys», «everyone»...) y la salida no tiene «vosotros» (marker), o
       - el estado de destinatario de la escena es «grupo» (hubo una marca de plural en las últimas 5 líneas y
         ninguna de singular) y la salida no tiene «vosotros» ni «ustedes» (state);
  4. reintento (solo marcadas): `note` = el mismo prompt con la nota de plural informal en el turno final;
     `note_bias` = lo anterior más `logit_bias` -100 a los tokens de «usted/ustedes» (ids de Hy-MT2-7B medidos con
     llama-tokenize: 61395 « usted», 28244 «usted», 24836 «sted»);
  5. se queda con el reintento si tiene «vosotros» y no tiene marcas de «ustedes»; si no, con la salida editada.

Mide el % de vosotros en P, el daño (S, F, T cambiadas), la fracción marcada f, el tiempo del reintento y el coste medio
por frase (todas las frases) = f × tiempo del reintento.

Uso: `uv run python b2_retry.py --variant base --retry note --state`
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "traduccion"))

import corpus_b0
import detector
import postedit
from common import OUT_DIR
from gpu_lock import gpu_lock
from instanttraductor.mt.hymt2 import max_tokens_for, rejection_reason
from llama_server import LlamaServer
from mt_lab import MODEL_7B, Client, clean_output, summarize_b0
from prompts_b1 import RETRY_NOTE, VARIANTS

USTED_TOKENS = {61395: -100.0, 28244: -100.0, 24836: -100.0}
_PLURAL_EN = re.compile(
    r"\b(you guys|you two|you three|you both|both of you|all of you|you all|y'all|everyone|everybody|guys|kids|"
    r"folks|team|class|crew|soldiers|friends|ladies and gentlemen|children|boys|girls|gentlemen)\b",
    re.IGNORECASE,
)
_SINGULAR_EN = re.compile(r"\b(buddy|sir|ma'am|madam|honey|sweetheart|kid|darling|mr\.|mrs\.|miss|detective)\b", re.IGNORECASE)
STATE_WINDOW = 5


def with_note(messages: list[dict]) -> list[dict]:
    out = [dict(m) for m in messages]
    out[-1]["content"] = out[-1]["content"] + "\n\n(" + RETRY_NOTE + ")"
    return out


def run(variant: str, retry: str, use_state: bool, seed: int) -> dict:
    build = VARIANTS[variant]
    records: list[dict] = []
    retry_ms: list[float] = []
    with gpu_lock():
        server = LlamaServer(model=MODEL_7B, extra_args=("--cache-ram", "0"), log_path=OUT_DIR / "llama_server.log")
        try:
            server.start()
            client = Client(server.base_url)
            by_scene: dict[int, list[corpus_b0.Line]] = {}
            for line in corpus_b0.LINES:
                by_scene.setdefault(line.scene, []).append(line)
            for scene, lines in by_scene.items():
                history: list[tuple[str, str]] = []
                english: list[str] = []
                for line in lines:
                    ctx = [(o, postedit.postedit_for_context(o, t)) for o, t in history[-4:]]
                    messages = build(line.text, ctx, [], False)
                    out, finish, ms, _ = client.complete(messages, max_tokens_for(line.text), seed)
                    out = clean_output(out)
                    reason = rejection_reason(line.text, out, finish_reason=finish)
                    raw = "" if reason else out.strip()
                    edited = postedit.postedit(line.text, raw)
                    text = edited.text
                    marks = detector.classify(text, line.text)
                    # estado de destinatario de la escena
                    recent = english[-STATE_WINDOW:]
                    group_state = any(_PLURAL_EN.search(x) for x in recent) and not any(_SINGULAR_EN.search(x) for x in recent)
                    flags = []
                    if "ust" in marks and "vos" not in marks:
                        flags.append("ust_left")
                    if _PLURAL_EN.search(line.text) and "vos" not in marks:
                        flags.append("marker")
                    addressed = bool(re.search(r"\b(you|your|yours)\b", line.text, re.IGNORECASE)) or detector._en_signals(line.text)[2]
                    if use_state and group_state and addressed and not (marks & {"vos", "ust"}) and not _SINGULAR_EN.search(line.text):
                        flags.append("state")
                    retried = False
                    if flags and retry != "none" and text:
                        retried = True
                        msgs2 = with_note(messages)
                        bias = USTED_TOKENS if retry == "note_bias" else None
                        t0 = time.perf_counter()
                        out2, fin2, ms2, _ = client.complete(msgs2, max_tokens_for(line.text), seed, logit_bias=bias)
                        out2 = clean_output(out2)
                        retry_ms.append(ms2)
                        if not rejection_reason(line.text, out2, finish_reason=fin2):
                            e2 = postedit.postedit(line.text, out2.strip())
                            m2 = detector.classify(e2.text, line.text)
                            if "vos" in m2 and "ust" not in m2:
                                text = e2.text
                        del t0
                    final = detector.primary(text, line.text)
                    records.append(
                        {
                            "idx": line.idx, "scene": scene, "label": line.label, "kind": line.kind, "marked": line.marked,
                            "source": line.text, "raw": raw, "raw_out": out, "finish": finish, "text": text, "primary": final,
                            "flags": flags, "retried": retried, "ms": ms, "rejected": reason, "prompt_n": None, "cache_n": None,
                            "changed_by_rules": edited.changed,
                        }
                    )
                    english.append(line.text)
                    if text:
                        history.append((line.text, text))
        finally:
            server.stop()
    n = len(records)
    flagged = [r for r in records if r["flags"]]
    summ = summarize_b0(records)
    summ["flagged"] = len(flagged)
    summ["flag_kinds"] = dict(Counter(f for r in flagged for f in r["flags"]))
    summ["retried"] = sum(1 for r in records if r["retried"])
    summ["flagged_by_label"] = dict(Counter(r["label"] for r in flagged))
    if retry_ms:
        s = sorted(retry_ms)
        summ["retry_ms_p50"] = s[len(s) // 2]
        summ["retry_ms_p95"] = s[int(len(s) * 0.95)]
        summ["retry_cost_per_sentence_ms"] = sum(retry_ms) / n
    summ["fixed_by_retry"] = sum(1 for r in records if r["retried"] and r["primary"] == "vos")
    summ["rules_changed"] = sum(1 for r in records if r["changed_by_rules"])
    return {"summary": summ, "records": records}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="base")
    ap.add_argument("--retry", default="note", choices=["none", "note", "note_bias"])
    ap.add_argument("--state", action="store_true")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    res = run(args.variant, args.retry, args.state, args.seed)
    name = f"b2_{args.variant}_{args.retry}{'_state' if args.state else ''}_s{args.seed}.json"
    (OUT_DIR / "mt" / name).write_text(json.dumps(res, ensure_ascii=False, indent=0), "utf-8")
    print(name, json.dumps(res["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
