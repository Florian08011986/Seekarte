#!/usr/bin/env python3
"""
kartenbild - macht aus dem OSM-Zwischenspeicher die Flaechen und Linien,
aus denen die gezeichnete Karte besteht.

Anlass: Das Luftbild hat eine harte Grenze. Gemessen am 2026-09-29 liefert
ArcGIS World_Imagery ueber dem Blindsee echte Aufnahmen nur bis Zoom 20; ab 21
kommt ein grauer Platzhalter mit HTTP 200 ("Map data not yet available").
Auch die amtlichen oesterreichischen Orthofotos hoeren dort auf (404 ab z20).
Eine gezeichnete Karte hat diese Grenze nicht - sie ist auf jeder Zoomstufe
scharf, weil nichts vergroessert wird.

Ausgabe: kartenbild.json, eine Sammlung von GeoJSON-Ebenen.
"""
import collections
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OSM_CACHE = os.path.join(HERE, "osm_cache.json")
AUSGABE = os.path.join(HERE, "kartenbild.json")

# Nachkommastellen: 5 entspricht rund 1 m. Mehr braucht keine Karte und
# kostet nur Dateigroesse.
GENAU = 5

# Flaechen, nach Zeichenreihenfolge (frueh = weiter unten)
FLAECHEN = [
    ("fels",   lambda t: t.get("natural") in ("scree", "bare_rock", "shingle")),
    ("wiese",  lambda t: t.get("landuse") in ("meadow", "farmland", "grass")
                      or t.get("natural") in ("grassland", "heath")),
    ("wald",   lambda t: t.get("landuse") == "forest" or t.get("natural") == "wood"),
    ("wasser", lambda t: t.get("natural") == "water" or "water" in t
                      or t.get("landuse") == "reservoir"),
]

# Linien
PFADE = {"path", "footway", "steps", "bridleway", "cycleway"}
FAHRWEGE = {"track", "service", "unclassified", "residential", "living_street"}
STRASSEN = {"primary", "secondary", "tertiary", "trunk", "motorway",
            "primary_link", "secondary_link", "trunk_link", "motorway_link"}


def runde(lat, lon):
    return [round(lon, GENAU), round(lat, GENAU)]


def main():
    daten = json.load(open(OSM_CACHE))
    els = daten["elements"]
    knoten = {e["id"]: (e["lat"], e["lon"]) for e in els if e["type"] == "node"}
    wege = [e for e in els if e["type"] == "way"]

    ebenen = collections.defaultdict(list)
    zaehler = collections.Counter()

    for w in wege:
        tags = w.get("tags", {}) or {}
        ns = [n for n in w.get("nodes", []) if n in knoten]
        if len(ns) < 2:
            continue
        punkte = [runde(*knoten[n]) for n in ns]
        geschlossen = ns[0] == ns[-1] and len(ns) >= 4

        # --- Flaechen ---
        if geschlossen:
            for name, trifft in FLAECHEN:
                if trifft(tags):
                    ebenen[name].append({
                        "type": "Feature",
                        "properties": {"name": tags.get("name", "")},
                        "geometry": {"type": "Polygon", "coordinates": [punkte]},
                    })
                    zaehler[name] += 1
                    break

        # --- Linien ---
        hw = tags.get("highway")
        if not hw:
            continue
        if hw in PFADE:
            ebene = "pfad"
        elif hw in FAHRWEGE:
            ebene = "fahrweg"
        elif hw in STRASSEN:
            ebene = "strasse"
        else:
            continue
        ebenen[ebene].append({
            "type": "Feature",
            "properties": {"art": hw, "name": tags.get("name", "")},
            "geometry": {"type": "LineString", "coordinates": punkte},
        })
        zaehler[ebene] += 1

    ausgabe = {name: {"type": "FeatureCollection", "features": merkmale}
               for name, merkmale in ebenen.items()}

    with open(AUSGABE, "w", encoding="utf-8") as f:
        json.dump(ausgabe, f, ensure_ascii=False, separators=(",", ":"))

    print(f"[kartenbild] {AUSGABE}  ({os.path.getsize(AUSGABE)/1024:.0f} KB)")
    for name, _ in FLAECHEN:
        print(f"[kartenbild]   Flaeche {name:8} {zaehler[name]:4}")
    for name in ("pfad", "fahrweg", "strasse"):
        print(f"[kartenbild]   Linie   {name:8} {zaehler[name]:4}")
    return ausgabe


if __name__ == "__main__":
    main()
