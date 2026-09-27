#!/usr/bin/env python3
"""
Baut index.html aus template.html + echten Routendaten.

  python3 build.py           # aus dem OSM-Cache bauen
  python3 build.py --fetch   # OSM-Daten vorher neu von Overpass holen
"""
import json
import os
import sys
import subprocess

import route_engine

HERE = os.path.dirname(os.path.abspath(__file__))

# Beschreibungstexte pro Rundenklasse. Die Kennzahlen kommen aus der Geometrie,
# hier steht nur, was die Runde ausmacht.
DESCRIPTIONS = {
    "mini":  "Kurze Runde direkt am Nordufer. Fester Untergrund, kaum Steigung — "
             "die entspannteste Art, ans Wasser zu kommen.",
    "kurz":  "Schattige Waldrunde etwas abseits des Ufers. Kühl auch an heißen "
             "Tagen und deutlich ruhiger als der Uferweg.",
    "see":   "Die klassische Umrundung des Blindsees — durchgehend am Wasser "
             "entlang, vorbei an Kiesstrand, Smaragdbucht und Versunkenem Wald.",
    "gross": "Seeumrundung plus Waldschleife im Hinterland. Mehr Höhenmeter, "
             "dafür die vollständige Auswahl an Aussichts- und Badeplätzen.",
    "pano":  "Die große Runde mit Aufstieg Richtung Fernpass und Zugspitzblick. "
             "Alpin, aussichtsreich und deutlich anspruchsvoller.",
}


def main():
    if "--fetch" in sys.argv:
        print("[build] hole OSM-Daten von Overpass…")
        subprocess.run([sys.executable, os.path.join(HERE, "fetch_osm.py")], check=True)

    hotspots = json.load(open(os.path.join(HERE, "hotspots.json"), encoding="utf-8"))
    print(f"[build] {len(hotspots)} Orte geladen")

    routes = route_engine.build_routes(hotspots, verbose=True)
    if not routes:
        raise SystemExit("[build] FEHLER: keine Runden gefunden")
    for r in routes:
        r["desc"] = DESCRIPTIONS.get(r["id"], "")

    osm = route_engine.load_osm()
    lake_ring = osm["lake_ring"]
    lake = {
        "name": osm["lake_name"],
        "center": [round(osm["lake_center"][1], 5), round(osm["lake_center"][0], 5)],
        "ring": [[round(p[1], 6), round(p[0], 6)] for p in lake_ring],
    }

    data = {"routes": routes, "hotspots": hotspots, "lake": lake}
    tpl = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
    if "__DATA__" not in tpl:
        raise SystemExit("[build] FEHLER: __DATA__-Platzhalter fehlt im Template")
    html = tpl.replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":")))

    out = os.path.join(HERE, "index.html")
    open(out, "w", encoding="utf-8").write(html)
    print(f"[build] geschrieben: {out}  ({len(html)/1024:.0f} KB, {len(routes)} Runden)")


if __name__ == "__main__":
    main()
