"""S6 · SC-004: tiempo de reanudación tras reiniciar la app (emisor controlado) y demo del vigilante.

La «app» es `emisor.py` (un tono continuo de -30 dBFS lanzado por el lanzador del venv, igual que cualquier
app con un proceso intermedio). El vigilante la busca por nombre, abre INCLUDE(raíz) y, al matarla, vuelve a
«esperando a la app». El tiempo de reanudación es: primer audio captado de la instancia nueva menos el
instante en que el emisor nuevo entrega su primer bloque de tono (`tone_start`, QPC compartido). Es lo
mismo que SC-004 («desde que vuelve a sonar») sin el arranque de la propia app.

Uso:
    uv run python spikes/captura_app/medir_reinicio.py [--n 5] [--poll 0.25]
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

import capturar_app as ca

HERE = Path(__file__).resolve().parent
CREATE_NO_WINDOW = 0x08000000


class Emitter:
    """Un emisor lanzado como proceso hijo; recoge sus líneas JSON en un hilo."""

    def __init__(self) -> None:
        self.t_spawn = time.perf_counter()
        self.proc = subprocess.Popen(
            [sys.executable, str(HERE / "emisor.py"), "--modo", "continuo", "--max-s", "120"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            creationflags=CREATE_NO_WINDOW,
        )
        self.lines: list[dict] = []
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for line in self.proc.stdout:
            try:
                self.lines.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    def tone_start(self, timeout: float = 15.0) -> float | None:
        end = time.perf_counter() + timeout
        while time.perf_counter() < end:
            for d in self.lines:
                if d.get("ev") == "tone_start":
                    return d["t_ns"] / 1e9
            time.sleep(0.01)
        return None

    def kill(self) -> float:
        subprocess.run(
            ["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
        )
        return time.perf_counter()


def stats(values: list[float]) -> str:
    if not values:
        return "n/d"
    return (
        f"min {min(values):.0f} / mediana {statistics.median(values):.0f} / max {max(values):.0f} ms (n={len(values)})"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=5, help="reinicios")
    ap.add_argument("--poll", type=float, default=0.25, help="sondeo del vigilante (s)")
    ap.add_argument("--espera", type=float, default=1.0, help="s entre morir y relanzar")
    args = ap.parse_args()

    matcher = ca.Matcher("python", "emisor.py")
    watcher = ca.AppWatcher(matcher, poll_s=args.poll, check_silent=False)
    watcher.start()
    time.sleep(1.0)
    print(f"Vigilante en marcha (sondeo {args.poll} s), estado: {watcher.state.value}", flush=True)

    resume, react_open, detect_death, cold = [], [], [], []
    em = Emitter()
    for k in range(args.n + 1):
        tone = em.tone_start()
        n_open = k + 1
        t_open = watcher.wait_for("ABIERTA", n_open, 20)
        t_audio = None
        end = time.perf_counter() + 15
        while time.perf_counter() < end and n_open not in watcher.first_audio_after_open:
            time.sleep(0.01)
        t_audio = watcher.first_audio_after_open.get(n_open)
        if tone is None or t_audio is None or t_open is None:
            print(f"  [{k}] medida incompleta (tone={tone}, audio={t_audio}, open={t_open})", flush=True)
        else:
            r = (t_audio - tone) * 1000
            o = (t_open - em.t_spawn) * 1000
            (cold if k == 0 else resume).append(r)
            react_open.append(o)
            print(
                f"  [{k}] {'arranque en frío' if k == 0 else 'reinicio'}: lanzado -> INCLUDE abierta {o:.0f} ms; "
                f"tono entregado -> primer audio captado {r:.0f} ms",
                flush=True,
            )
        time.sleep(1.0)  # un segundo de audio estable
        if k == args.n:
            break
        t_kill = em.kill()
        t_dead = watcher.wait_for("MUERTA", k + 1, 10)
        if t_dead is not None:
            detect_death.append((t_dead - t_kill) * 1000)
        time.sleep(args.espera)
        assert watcher.state is ca.State.WAITING, watcher.state
        em = Emitter()
    em.kill()
    watcher.stop()

    print()
    print(f"Sondeo del vigilante: {args.poll} s; reinicios: {args.n}")
    print(f"  lanzamiento -> INCLUDE abierta (incluye crear el proceso): {stats(react_open)}")
    print(f"  muerte -> detectada por el vigilante: {stats(detect_death)}")
    print(f"  REANUDACIÓN tras reinicio (tono entregado -> audio captado): {stats(resume)}")
    print(f"  arranque en frío (la app no existía): {stats(cold)}")
    print(f"  avisos de la fuente (ProcessLoopbackSource): {len(watcher.warnings)} {watcher.warnings[:3]}")
    print(f"  aperturas: {watcher.open_count}; estado final: {watcher.state.value}")


if __name__ == "__main__":
    main()
