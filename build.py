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

# Zweite Textfassung fuer den Kinderwagen-Modus. Beschreibt, was der Ausflug
# mit Wagen praktisch bedeutet - die Zahlen dahinter kommen aus route_engine.
DESCRIPTIONS_KW = {
    "mini":  "Die unkomplizierteste Runde: fester Untergrund, keine Stufen, "
             "in einer knappen halben Stunde zu schaffen. Zwei kurze Rampen "
             "gleich am Anfang und nach 600 m, sonst durchgehend flach. Am "
             "Start steht eine Bank.",
    "kurz":  "Schattige Waldrunde — angenehm, wenn die Sonne drückt. Der Weg "
             "ist fest, aber es geht mehrfach spürbar bergauf: zusammen gut "
             "450 m zum Schieben. Unterwegs steht keine Bank, also besser "
             "eine Pausendecke einpacken.",
    "see":   "Die schönste Strecke am Wasser, aber mit Wagen nur mit Hilfe: "
             "auf halber Strecke liegen zwei kurze Treppenstücke, da muss der "
             "Wagen getragen werden. Dafür stehen sieben Bänke an der Runde, "
             "sechs davon dicht beieinander als Rastplatz.",
    "gross": "Lange Runde mit vielen Wechseln. Auch hier Treppen auf der "
             "Strecke und mehrere längere Anstiege — mit Wagen anstrengend, "
             "aber es gibt reichlich Bänke zum Verschnaufen.",
    "pano":  "Die anspruchsvollste Runde: über zwei Stunden, mehrere hundert "
             "Meter steile Abschnitte und Treppen. Mit Kinderwagen nicht zu "
             "empfehlen — mit Kraxe dagegen eine schöne Tour.",
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
        r["desc_kw"] = DESCRIPTIONS_KW.get(r["id"], "")

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
