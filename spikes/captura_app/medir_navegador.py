"""S6 · SC-003 y SC-004 con un navegador real (Chrome o Edge) reproduciendo un vídeo.

Todo el audio que se analiza es PROPIO (un vídeo con un seno de 1234 Hz a -30 dBFS que genera ffmpeg y una voz
de SAPI que reproduce ffplay): nada de terceros se escucha, se guarda ni se analiza. El navegador usa un perfil
temporal propio (`--user-data-dir`), así que es una instancia aparte del Chrome/Edge de uso real y su audio no
se mezcla con el de la persona.

Fases (una sola instancia del navegador, un solo INCLUDE sobre su proceso raíz):
  A  la página aún no suena y ffplay reproduce una voz en español: la captura INCLUDE(navegador) debe ser
     silencio digital (SC-003: otra app no entra).
  B  el vídeo empieza a sonar mientras la voz sigue: debe aparecer el tono y NO la voz.
  C  se para la voz: línea base (el vídeo solo).
  D  se mata el navegador y se relanza: tiempo de reanudación (SC-004) = primer audio captado - evento
     `playing` del vídeo (lo avisa la página a un servidor local).
Control positivo: una segunda captura INCLUDE(ffplay) debe oír la voz en A y B (si no, la prueba no vale).

Uso:
    uv run python spikes/captura_app/medir_navegador.py [--browser chrome|edge] [--fase-b 20] [--workdir DIR]
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path

import capturar_app as ca
import common as c
import numpy as np
import psutil
from instanttraductor.audio.selftest import TONE_HZ, tone_ratio_db

RATE = 16000
CREATE_NO_WINDOW = 0x08000000
BROWSERS = {
    "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "edge": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
}
PAGE = """<!doctype html><meta charset="utf-8"><title>S6</title>
<video id="v" src="video.mp4" loop width="320" height="180"></video>
<script>
const d = parseFloat(new URLSearchParams(location.search).get('d') ?? '14');
const v = document.getElementById('v');
v.addEventListener('playing', () => fetch('/beacon?ev=playing&r=' + Math.random()));
fetch('/beacon?ev=loaded&r=' + Math.random());
setTimeout(() => v.play(), d * 1000);
</script>
"""
VOICE_TEXT = (
    "Esta es una frase de prueba en español. No debe traducirse, porque no viene de la aplicación elegida. "
    "Estoy hablando desde otro programa mientras el vídeo suena en el navegador."
)


def dbfs(x: float) -> float:
    return c.db(x)


# --------------------------------------------------------------------------------------------------
# Preparación (ficheros temporales propios)
# --------------------------------------------------------------------------------------------------


def make_assets(workdir: Path) -> tuple[Path, float]:
    """Crea video.mp4 (seno de 1234 Hz a -30 dBFS), page.html y voz.wav (SAPI, pico a -30 dBFS)."""
    workdir.mkdir(parents=True, exist_ok=True)
    video = workdir / "video.mp4"
    if not video.exists():
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc=size=320x180:rate=10",
                "-f", "lavfi", "-i", "sine=frequency=1234:sample_rate=48000",
                "-af", "volume=-12dB", "-t", "6", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                "-shortest", str(video),
            ],
            check=True,
        )  # fmt: skip
    (workdir / "page.html").write_text(PAGE, encoding="utf-8")
    voice = workdir / "voz.wav"
    if not voice.exists():
        ps = (
            "Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$s.SetOutputToWaveFile('{voice}'); $s.Speak('{VOICE_TEXT}'); $s.Dispose()"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    with wave.open(str(voice)) as w:
        raw = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
    peak = float(np.max(np.abs(raw)))
    gain_db = -30.0 - dbfs(peak)  # pico de la voz a -30 dBFS
    return voice, gain_db


class Beacons:
    """Servidor local: sirve la página y apunta cuándo el vídeo dice `playing` (reloj perf_counter)."""

    def __init__(self, workdir: Path) -> None:
        self.events: list[tuple[float, str]] = []
        beacons = self

        class Handler(http.server.SimpleHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path.startswith("/beacon"):
                    ev = "playing" if "ev=playing" in self.path else "loaded"
                    beacons.events.append((time.perf_counter(), ev))
                    self.send_response(204)
                    self.end_headers()
                else:
                    super().do_GET()

            def log_message(self, *args) -> None:
                pass

        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        sock.close()
        self.server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", self.port), functools.partial(Handler, directory=str(workdir))
        )
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def first(self, ev: str, after: float) -> float | None:
        return next((t for t, e in self.events if e == ev and t >= after), None)

    def close(self) -> None:
        self.server.shutdown()


# --------------------------------------------------------------------------------------------------
# Navegador y voz
# --------------------------------------------------------------------------------------------------


class Browser:
    def __init__(self, exe: str, profile: Path, url: str) -> None:
        self.exe, self.profile, self.url = exe, profile, url
        self.t_launch = 0.0

    def launch(self, delay_s: float) -> None:
        self.t_launch = time.perf_counter()
        subprocess.Popen(
            [
                self.exe, f"--user-data-dir={self.profile}", "--no-first-run", "--no-default-browser-check",
                "--autoplay-policy=no-user-gesture-required", "--start-minimized", "--window-size=400,300",
                "--disable-sync", "--disable-extensions", f"{self.url}?d={delay_s}",
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW,
        )  # fmt: skip

    def matcher(self) -> ca.Matcher:
        return ca.Matcher(Path(self.exe).stem, self.profile.name)

    def processes(self) -> list[c.ProcInfo]:
        return ca.snapshot_matching(self.matcher())

    def kill(self) -> float:
        for info in self.processes():
            try:
                psutil.Process(info.pid).kill()
            except psutil.NoSuchProcess:
                pass
        return time.perf_counter()


def start_voice(workdir: Path, gain_db: float) -> subprocess.Popen:
    return subprocess.Popen(
        ["ffplay", "-nodisp", "-autoexit", "-loop", "0", "-loglevel", "quiet",
         "-af", f"volume={gain_db:.1f}dB", str(workdir / "voz.wav")],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW,
    )  # fmt: skip


def kill_tree(proc: subprocess.Popen) -> float:
    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    return time.perf_counter()


# --------------------------------------------------------------------------------------------------
# Análisis (solo del audio propio)
# --------------------------------------------------------------------------------------------------


class Recorder:
    """Guarda en memoria (audio propio) los chunks con su hora de llegada."""

    def __init__(self) -> None:
        self.items: list[tuple[float, np.ndarray]] = []

    def __call__(self, samples: np.ndarray, arrival: float, _t: float) -> None:
        self.items.append((arrival, samples))

    def segment(self, t0: float, t1: float) -> np.ndarray:
        parts = [s for t, s in list(self.items) if t0 <= t < t1]
        return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x.astype(np.float64) ** 2))) if len(x) else 0.0


def residual_rms(x: np.ndarray, hz: float = TONE_HZ, half_band: float = 60.0) -> float:
    """RMS de lo que queda al quitar el tono de 1234 Hz (± 60 Hz): lo que NO es el vídeo."""
    if len(x) < 1024:
        return 0.0
    spec = np.fft.rfft(x.astype(np.float64))
    freqs = np.fft.rfftfreq(len(x), 1 / RATE)
    spec[np.abs(freqs - hz) <= half_band] = 0
    return rms(np.fft.irfft(spec, len(x)))


def describe(label: str, x: np.ndarray) -> dict:
    ratio = tone_ratio_db(x.astype(np.float32), RATE) if len(x) >= 0.3 * RATE else 0.0
    out = {
        "fase": label,
        "s": round(len(x) / RATE, 1),
        "rms_dbfs": round(dbfs(rms(x)), 1),
        "residuo_dbfs": round(dbfs(residual_rms(x)), 1),
        "tono_1234_db": round(ratio, 1),
    }
    print(
        f"  {label:<34s} {out['s']:5.1f} s  rms {out['rms_dbfs']:7.1f} dBFS  sin el tono {out['residuo_dbfs']:7.1f} dBFS"
        f"  tono 1234 Hz: {out['tono_1234_db']:6.1f} dB",
        flush=True,
    )
    return out


# --------------------------------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--browser", choices=BROWSERS, default="chrome")
    ap.add_argument("--fase-b", type=float, default=20.0, help="segundos con voz y vídeo a la vez")
    ap.add_argument("--fase-a", type=float, default=8.0, help="segundos de voz sola (la página aún calla)")
    ap.add_argument("--workdir", default="")
    ap.add_argument("--reinicios", type=int, default=3)
    args = ap.parse_args()

    workdir = Path(args.workdir) if args.workdir else Path(tempfile.gettempdir()) / "s6_captura"
    voice, gain_db = make_assets(workdir)
    profile = workdir / f"perfil_{args.browser}_{int(time.time())}"
    beacons = Beacons(workdir)
    browser = Browser(BROWSERS[args.browser], profile, f"http://127.0.0.1:{beacons.port}/page.html")
    result: dict = {"navegador": args.browser}

    rec_browser, rec_voice = Recorder(), Recorder()
    w_browser = ca.AppWatcher(browser.matcher(), on_chunk=rec_browser, check_silent=False, verbose=True)
    w_voice = ca.AppWatcher(ca.Matcher("ffplay"), on_chunk=rec_voice, check_silent=False, verbose=False)
    browser.processes()  # calienta la caché de línea de comandos de los Chrome/Edge ya abiertos (lenta, solo pruebas)
    w_browser.start()
    voice_proc = None
    delay = args.fase_a + 8.0  # margen para que el navegador cargue y el vigilante abra la captura
    try:
        print(f"Navegador: {args.browser}, perfil temporal {profile.name}; voz con pico a -30 dBFS", flush=True)
        browser.launch(delay)
        w_browser.wait_for("ABIERTA", 1, 30)
        t_open = time.perf_counter()
        # Voz de otra app (ffplay) mientras la página aún no suena
        t_voice = time.perf_counter()
        voice_proc = start_voice(workdir, gain_db)
        w_voice.start()
        t_play = None
        end = time.perf_counter() + delay + 15
        while time.perf_counter() < end and t_play is None:
            t_play = beacons.first("playing", browser.t_launch)
            time.sleep(0.05)
        if t_play is None:
            raise SystemExit("el vídeo no llegó a reproducirse (¿autoplay bloqueado?)")
        print(f"  voz iniciada {t_voice - t_open:+.1f} s respecto a la apertura; el vídeo suena a los "
              f"{t_play - t_voice:.1f} s de la voz", flush=True)  # fmt: skip
        time.sleep(args.fase_b)
        t_stop_voice = kill_tree(voice_proc)
        time.sleep(1.0)
        t_c0 = time.perf_counter()
        time.sleep(6.0)
        t_c1 = time.perf_counter()

        print("\nSC-003: INCLUDE(navegador) con la voz de otra app sonando (audio propio, solo métricas):")
        a_start, a_end = t_voice + 2.0, t_play - 0.5
        b_start, b_end = t_play + 1.5, t_stop_voice - 0.3
        result["A"] = describe("A  navegador mudo + voz ffplay", rec_browser.segment(a_start, a_end))
        result["A_control"] = describe("A  control: INCLUDE(ffplay) = voz", rec_voice.segment(a_start, a_end))
        result["B"] = describe("B  vídeo + voz a la vez", rec_browser.segment(b_start, b_end))
        result["B_control"] = describe("B  control: INCLUDE(ffplay) = voz", rec_voice.segment(b_start, b_end))
        result["C"] = describe("C  solo vídeo (línea base)", rec_browser.segment(t_c0, t_c1))
        a, b, base = result["A"], result["B"], result["C"]
        control_ok = result["A_control"]["rms_dbfs"] > -60 and result["B_control"]["rms_dbfs"] > -60
        leak_a = a["rms_dbfs"] > -90
        leak_b = b["residuo_dbfs"] > max(base["residuo_dbfs"], -90) + 3
        tone_ok = b["tono_1234_db"] >= 15 and base["tono_1234_db"] >= 15
        verdict = control_ok and not leak_a and not leak_b and tone_ok
        result["SC003"] = {
            "control_voz_oida": control_ok, "fuga_en_A": leak_a, "fuga_en_B": leak_b,
            "tono_del_navegador_oido": tone_ok, "ok": verdict,
        }  # fmt: skip
        print(f"  => SC-003 en esta medida: {'CORRECTO' if verdict else 'FALLO'} {result['SC003']}", flush=True)

        # --- D: reinicios del navegador ---------------------------------------------------------
        print(
            f"\nSC-004: {args.reinicios} reinicios del navegador (matar todos sus procesos y relanzar):",
            flush=True,
        )
        resume, to_open, detect = [], [], []
        for k in range(args.reinicios):
            t_kill = browser.kill()
            t_dead = next((t for t in w_browser.event_times("MUERTA") if t >= t_kill), None)
            end = time.perf_counter() + 10
            while t_dead is None and time.perf_counter() < end:
                time.sleep(0.01)
                t_dead = next((t for t in w_browser.event_times("MUERTA") if t >= t_kill), None)
            if t_dead:
                detect.append((t_dead - t_kill) * 1000)
            time.sleep(1.5)
            beacons.events.clear()
            browser.launch(0.0)
            t_play2 = t_audio = None
            end = time.perf_counter() + 25
            while time.perf_counter() < end:
                t_play2 = beacons.first("playing", browser.t_launch)
                audios = [(n, t) for n, t in w_browser.first_audio_after_open.items() if t >= browser.t_launch]
                if t_play2 and audios:
                    n_audio, t_audio = min(audios, key=lambda x: x[1])
                    break
                time.sleep(0.02)
            if t_play2 and t_audio:
                opens = [t for t in w_browser.open_times.values() if t >= browser.t_launch]
                to_open.append((min(opens) - browser.t_launch) * 1000)
                resume.append((t_audio - t_play2) * 1000)
                stubs = len(opens) - 1
                print(
                    f"  [{k + 1}] lanzado -> 1ª INCLUDE abierta {to_open[-1]:.0f} ms; lanzado -> vídeo suena "
                    f"{(t_play2 - browser.t_launch) * 1000:.0f} ms; vídeo suena -> audio captado {resume[-1]:.0f} ms"
                    f"{f' ({stubs} reapertura(s) por procesos lanzadores efímeros)' if stubs else ''}",
                    flush=True,
                )
            else:
                print(f"  [{k + 1}] medida incompleta (playing={t_play2}, audio={t_audio})")
            time.sleep(2.0)
        result["SC004"] = {
            "reanudacion_ms": [round(x) for x in resume],
            "lanzado_a_abierta_ms": [round(x) for x in to_open],
            "muerte_a_detectada_ms": [round(x) for x in detect],
        }
        print(f"  muerte -> detectada: {detect}\n  vídeo suena -> audio captado (reanudación): {resume}")
    finally:
        w_browser.stop()
        w_voice.stop()
        browser.kill()
        if voice_proc is not None:
            kill_tree(voice_proc)
        beacons.close()
        time.sleep(1.0)
        shutil.rmtree(profile, ignore_errors=True)
    print("\nJSON:", json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
