"""Busca en Wikimedia Commons música instrumental con licencia libre (CC0 o dominio público) y la descarga.

Solo se aceptan licencias CC0 / dominio público (no pide atribución). Imprime la licencia y el autor de cada
fichero para anotarlos en el README. Uso: `uv run python find_music.py list|get <n_ficheros>`.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request

from common import DL_DIR

QUERIES = [
    'incategory:"CC-Zero" filetype:audio orchestral',
    'incategory:"CC-Zero" filetype:audio piano',
    'incategory:"CC-Zero" filetype:audio ambient',
    'incategory:"CC-Zero" filetype:audio instrumental',
    'incategory:"CC-Zero" filetype:audio guitar',
]


def search(query: str) -> list[dict]:
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(
        {
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": 6,
            "gsrlimit": 40,
            "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata",
            "format": "json",
        }
    )
    req = urllib.request.Request(url, headers={"User-Agent": "InstantTraductor-spike/0.1 (personal research)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    out = []
    for page in data.get("query", {}).get("pages", {}).values():
        info = page["imageinfo"][0]
        meta = info["extmetadata"]
        out.append(
            {
                "title": page["title"],
                "url": info["url"],
                "size": info["size"],
                "mime": info["mime"],
                "license": meta.get("LicenseShortName", {}).get("value", "?"),
                "artist": meta.get("Artist", {}).get("value", "?")[:60].replace("\n", " "),
            }
        )
    return out


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "list"
    seen: dict[str, dict] = {}
    cache = DL_DIR / "music_search.json"
    if cache.exists():
        found = json.loads(cache.read_text("utf-8"))
    else:
        found = []
        for q in QUERIES:
            found.extend(search(q))
            time.sleep(8)
        cache.write_text(json.dumps(found), "utf-8")
    for item in found:
        if item["license"].lower().startswith(("cc0", "public domain", "cc-zero")):
            seen[item["title"]] = item
    cands = sorted(seen.values(), key=lambda i: i["size"])
    cands = [c for c in cands if 800_000 < c["size"] < 25_000_000 and c["mime"].startswith(("audio/", "application/ogg"))]
    for c in cands:
        print(f"{c['size'] // 1024:>7} KB  {c['mime']:<16} {c['license']:<10} {c['title'][:70]}  |  {c['artist']}")
    if mode == "get":
        wanted = sys.argv[2:]
        meta = []
        for c in [c for c in cands if any(w.lower() in c["title"].lower() for w in wanted)]:
            name = c["title"].removeprefix("File:").replace("/", "_")
            dest = DL_DIR / "music" / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                req = urllib.request.Request(c["url"], headers={"User-Agent": "InstantTraductor-spike/0.1 (personal research)"})
                for attempt in range(6):  # Wikimedia limita las descargas: se reintenta con espera
                    try:
                        with urllib.request.urlopen(req, timeout=120) as r:
                            data = r.read()
                        dest.write_bytes(data)
                        break
                    except urllib.error.HTTPError as err:
                        if err.code != 429:
                            raise
                        time.sleep(20 * (attempt + 1))
                time.sleep(8)
            meta.append({k: c[k] for k in ("title", "url", "license", "artist")})
            print("descargado", dest)
        (DL_DIR / "music" / "music_sources.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), "utf-8")


if __name__ == "__main__":
    main()
