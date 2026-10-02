"""Descarga música libre de Wikimedia Commons (dominio público / CC0) para mezclar con el habla.

Cada pista se descarga a ``%LOCALAPPDATA%\\InstantTraductor\\spikes\\idiomas\\music\\`` y se convierte a WAV mono de 16 kHz.
La licencia y la procedencia salen de los metadatos de Commons y se guardan en ``music_licenses.json`` (en el repo).
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request

import numpy as np
import soundfile as sf
import soxr

from idiomas.paths import SPIKE_DIR, music_dir

API = "https://commons.wikimedia.org/w/api.php"
UA = "InstantTraductorSpike/0.1 (investigacion personal; claudiocodediepau@gmail.com)"

#: Pistas de la categoría Musopen de Commons (grabaciones orquestales y de piano de dominio público).
TITLES = [
    "File:Alexander Borodin - In The Steppes Of Central Asia.ogg",
    "File:Antonin Dvorak - symphony no. 9 in e minor 'from the new world', op. 95 - ii. largo.ogg",
    "File:Antonin Dvorak - symphony no. 9 in e minor 'from the new world', op. 95 - iv. allegro con fuoco.ogg",
    "File:Albinoni, Concerto for Oboe and Strings No. 2 in D minor, Op. 9, I. Allegro e con presto.ogg",
]


def api(**params: str) -> dict:
    url = API + "?" + urllib.parse.urlencode({"format": "json", **params})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return json.load(urllib.request.urlopen(req, timeout=60))


def plain(html: str | None) -> str | None:
    """Texto sin etiquetas HTML (los metadatos de Commons vienen con enlaces)."""
    return None if html is None else re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html)).strip()


#: Pistas con voz cantada (aria y coros) para probar qué pasa cuando el VAD sí se activa: ``--vocal``.
VOCAL_TITLES = [
    "File:Wolfgang Amadeus Mozart - cosi fan tutte act ii - no. 19 aria - una donna a quindici anni.ogg",
    "File:Giuseppe Verdi - Anvil Chorus.ogg",
    "File:Richard Wagner - Treulich geführt.ogg",
]


def main() -> None:
    vocal = "--vocal" in sys.argv
    titles, prefix = (VOCAL_TITLES, "vocal") if vocal else (TITLES, "track")
    meta = []
    for title in titles:
        data = api(action="query", titles=title, prop="imageinfo", iiprop="url|extmetadata|size|mime")
        page = next(iter(data["query"]["pages"].values()))
        info = page["imageinfo"][0]
        ext = info["extmetadata"]
        lic = ext.get("LicenseShortName", {}).get("value", "?")
        artist = ext.get("Artist", {}).get("value", "?")
        print(title, "->", lic, "|", (plain(artist) or "?")[:80], "|", info["size"] // 1_000_000, "MB", flush=True)
        stem = f"{prefix}{len(meta) + 1}"
        raw = music_dir() / f"{stem}{'.ogg' if info['mime'].endswith('ogg') else '.bin'}"
        if not raw.exists():
            req = urllib.request.Request(info["url"], headers={"User-Agent": UA})
            raw.write_bytes(urllib.request.urlopen(req, timeout=300).read())
        audio, sr = sf.read(raw, always_2d=True, dtype="float32")
        mono = audio.mean(axis=1)
        mono = soxr.resample(mono, sr, 16_000)
        wav = music_dir() / f"{stem}.wav"
        sf.write(wav, mono.astype(np.float32), 16_000, subtype="PCM_16")
        meta.append(
            {
                "file": wav.name,
                "title": title,
                "url": info["descriptionurl"],
                "license": lic,
                "license_url": ext.get("LicenseUrl", {}).get("value"),
                "artist": plain(artist),
                "credit": plain(ext.get("Credit", {}).get("value")),
                "seconds": round(len(mono) / 16_000, 1),
            }
        )
    (SPIKE_DIR / ("music_licenses_vocal.json" if vocal else "music_licenses.json")).write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
