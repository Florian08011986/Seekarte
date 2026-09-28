# 🏔️ Blindsee · Tourenkarte

Interaktive 3D-Karte mit **echten, berechneten Rundwegen** rund um den Blindsee in Tirol.

![Blindsee 3D](blindsee_screenshot.png)

## Was die Karte kann

- **Echte Rundwege statt gezeichneter Linien.** Alle Touren sind geschlossene
  Runden, die aus dem OSM-Wegenetz berechnet werden — Start = Ziel. Jede
  Kilometer-, Höhenmeter- und Steigungsangabe stammt aus der Geometrie.
- **Tour-Assistent mit vier Fragen**, die zusammen bestimmen, welche Runde
  wirklich passt: gewünschte Rundengröße, Begleitung (Kinderwagen, kleine
  Kinder, Hund, sportlich), akzeptierte Steigung und Schwerpunkte (Wasser,
  Aussicht, Schatten, Sehenswürdigkeiten, Ruhe). Harte Anforderungen filtern,
  weiche Wünsche gewichten — und der Vorschlag wird begründet.
- **Vor-Ort-Ansicht in 3D.** Die Kamera wird auf Geländehöhe an den Ort gesetzt;
  per Ziehen schaut man sich um. Wo offene Bodenfotos existieren
  ([Panoramax](https://panoramax.xyz)), gibt es zusätzlich das echte Foto.
- **Kinderwagen-Modus** (👶 in der Kopfzeile): Kinderwagen-Ampel je Runde mit
  Begründung, Rastpunkte aus OSM auf der Karte, eine Zeitleiste mit allen
  Stellen zum Schieben und Tragen samt Kilometerangabe, größere Bedienflächen
  und ein auf zwei Fragen verkürzter Assistent.
- **Bedienung über ein Bottom-Sheet** in drei Stufen (Vorschau / halb / ganz)
  mit den Reitern Runden · Orte · Details, plus Höhenprofil je Runde.

## Die Runden

Berechnet aus dem OpenStreetMap-Wegenetz; die Werte erzeugt `route_engine.py`:

| Runde | Länge | Höhenmeter | Am Ufer | Schatten | Bänke | Kinderwagen |
|---|---|---|---|---|---|---|
| Kleine Uferrunde | 1,41 km | 22 Hm | 77 % | – | 1 | 🟢 problemlos |
| Kurze Waldrunde | 2,13 km | 55 Hm | – | 63 % | 0 | 🟡 machbar |
| Seeumrundung | 3,64 km | 66 Hm | 100 % | – | 7 | 🔴 Treppen |
| Große Runde | 5,94 km | 135 Hm | 58 % | – | 7 | 🔴 Treppen |
| Panorama-Runde | 7,78 km | 231 Hm | 34 % | – | 15 | 🔴 Treppen |

Die Kinderwagen-Ampel ist bewusst dreistufig: Ein Ja/Nein hätte die schönste
Runde am Ufer allein wegen des naturbelassenen Untergrunds aussortiert. Rot
steht hier nicht für „zu steil", sondern für die 16 m Treppen auf halber
Strecke, an denen der Wagen getragen werden muss.

## Aufbau

| Datei | Zweck |
|---|---|
| `index.html` | fertige Anwendung (wird generiert — nicht direkt bearbeiten) |
| `template.html` | Quelle für Oberfläche, Stile und Logik; `__DATA__` wird beim Build ersetzt |
| `route_engine.py` | findet und bewertet die Rundwege im Wegenetz |
| `build.py` | setzt Template und berechnete Daten zu `index.html` zusammen |
| `fetch_osm.py` | holt die OSM-Rohdaten von Overpass nach `osm_cache.json` |
| `hotspots.json` | die redaktionellen Ortsinhalte (Kosten, Zeiten, Regeln) |
| `osm_cache.json` | zwischengespeicherte OSM-Daten, damit der Build offline läuft |
| `dem_wide.asc` | Höhenmodell-Ausschnitt für Höhenmeter und Steigung |

## Neu bauen

```bash
python3 build.py            # aus dem Cache bauen (dauert ~2 Min: Ringsuche)
python3 build.py --fetch    # OSM-Daten vorher frisch von Overpass holen
```

Nur Standardbibliothek, keine Abhängigkeiten. Für einen neuen
Höhenmodell-Ausschnitt wird `gdal_translate` und die (nicht versionierte)
Kachel `dem_N47_E010.tif` gebraucht — für einen normalen Build reicht das
mitgelieferte `dem_wide.asc`.

Lokal ansehen:

```bash
python3 -m http.server 8088   # dann http://127.0.0.1:8088/
```

## Wie die Runden gefunden werden

1. Wegenetz als Graph aufbauen (Verbindung über gemeinsame OSM-Knoten)
2. Grad-2-Ketten zu Super-Kanten kontrahieren → kleiner Kreuzungsgraph
3. Fundamentalzyklen über einen Spannbaum bestimmen
4. Benachbarte Zyklen per XOR zu größeren Ringen kombinieren
5. Pro Längenklasse den Ring wählen, der kompakt **und** nah am Wasser ist
6. Rastpunkte (Bänke, WC, Trinkwasser, Unterstände) und zusammenhängende
   Steigungs- und Treppenabschnitte mit Position ab Start zuordnen
7. Mit echten Kennzahlen anreichern: Höhenprofil aus dem DEM (bilinear
   interpoliert, auf 50-m-Schritte resampelt), Belag und Treppen aus den
   OSM-Tags, Schattenanteil aus Waldflächen, Uferanteil aus einem
   vorberechneten Abstandsraster

## Grenzen

- **Kein Street View.** Echte Bodenfotos gibt es über Panoramax nur dort, wo
  jemand welche aufgenommen hat — am Blindsee im Wesentlichen entlang der
  B179, nicht auf den Uferpfaden. Für alle anderen Orte zeigt die
  Vor-Ort-Ansicht das 3D-Gelände. MapLibre kann die Kamera nicht frei
  platzieren, deshalb steht sie je nach Zoom einige Meter über dem Boden statt
  exakt auf Augenhöhe.
- Steigungswerte stammen aus einem ~30-m-Höhenmodell. Kurze Rampen können
  dadurch geglättet sein.
- Rastpunkte und WCs stammen aus OpenStreetMap und sind dort unvollständig:
  im Umkreis von 1,5 km um den See ist kein WC verzeichnet, obwohl es am
  Bootshaus welche geben soll.
- Die Wegequalität hängt an den OSM-Tags. Wo `surface` fehlt, wird neutral
  bewertet — die Kinderwagen-Einstufung ist ein Anhaltspunkt, keine Garantie.

## Daten

Wege und Orte © OpenStreetMap-Mitwirkende (ODbL) · Luftbild © Esri, Maxar,
Earthstar Geographics · Höhendaten Mapzen/AWS Terrain Tiles ·
Bodenfotos © Panoramax-Mitwirkende (CC-BY-SA)

## Lizenz

MIT
