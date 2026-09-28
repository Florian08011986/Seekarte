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
- **Schattenzeiten.** Für Stützpunkte entlang jeder Runde ist aus dem
  Höhenmodell ein Horizontprofil vorberechnet (12 Himmelsrichtungen, Berge bis
  10 km Entfernung). Die Karte rechnet dazu den Sonnenstand und zeigt den
  Schattenanteil über den Tag — die Linie färbt sich sonnig/schattig.
- **Tour-Kamera auf festem Pfad.** Die Kamera fährt die Runde ab: Position und
  Blickrichtung kommen aus der Linie, die Neigung wird automatisch so weit
  zurückgenommen, dass das Gelände davor die Sicht nicht schneidet. Bedient
  über Schieberegler und Abspielknopf. Wo offene Bodenfotos existieren
  ([Panoramax](https://panoramax.xyz)), gibt es zusätzlich das echte Foto.
- **Kinderwagen-Modus** (👶 in der Kopfzeile): Kinderwagen-Ampel je Runde mit
  Begründung, Rastpunkte aus OSM auf der Karte, eine Zeitleiste mit allen
  Stellen zum Schieben und Tragen samt Kilometerangabe, größere Bedienflächen
  und ein auf zwei Fragen verkürzter Assistent.
- **Runden anpassen.** Startpunkt frei wählbar (die Runde wird gedreht, Länge
  bleibt gleich), alternative Streckenführungen wo das Wegenetz sie hergibt,
  Abstecher zu lohnenden Zielen über echte Wege — und eigene Punkte (WC,
  Wickelraum, Parkplatz, Bank), die sich auch als Startpunkt wählen lassen.
- **GPX-Export** je Runde — inklusive Wegpunkten für Orte, Rastpunkte, eigene
  Punkte und Warnmarken an den Treppen. Läuft in Komoot, OsmAnd, Garmin.
- **Interaktives Höhenprofil**, nach Steigung eingefärbt: beim Fahren über das
  Profil wandert eine Marke auf der Karte mit, mit Kilometer, Höhe und Prozent.
- **Höhenlinien** zuschaltbar (⛰), gerechnet im Browser aus denselben
  Terrain-Kacheln, die die Karte ohnehin lädt — keine zusätzliche Datenquelle.
- **Filterleiste** über Länge, Kinderwagen-Ampel und Eigenschaften (am Wasser,
  Schatten, viele Bänke, viel zu sehen, flach) mit laufender Trefferzahl.
- **Bedienung über ein Bottom-Sheet** in drei Stufen (Vorschau / halb / ganz)
  mit den Reitern Runden · Details · Anpassen · Orte, plus Höhenprofil je Runde.

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
| `shade.py` | Horizontprofile und Waldanteil je Stützpunkt |
| `shade_cache.json` | vorberechnete Horizontprofile, damit der Build ohne die DEM-Kachel läuft |
| `build.py` | setzt Template und berechnete Daten zu `index.html` zusammen |
| `fetch_osm.py` | holt die OSM-Rohdaten von Overpass nach `osm_cache.json` |
| `hotspots.json` | die redaktionellen Ortsinhalte (Kosten, Zeiten, Regeln) |
| `osm_cache.json` | zwischengespeicherte OSM-Daten, damit der Build offline läuft |
| `dem_wide.asc` | Höhenmodell-Ausschnitt für Höhenmeter und Steigung |
| `variants.json` | alternative Streckenführungen, wird erst beim Anpassen nachgeladen |

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
  B179, nicht auf den Uferpfaden. Für alle anderen Stellen zeigt die
  Tour-Kamera das 3D-Gelände. MapLibre kann die Kamera nicht frei platzieren,
  deshalb bleibt sie einige Meter über dem Boden; freies Umsehen gibt es
  bewusst nicht, weil die Kamera dabei in den Hang gerät und man durch das
  Gelände hindurchsieht.
- **Schattenzeiten sind Geländeschatten**, kein Wetter: bei Bewölkung ist
  ohnehin alles im Schatten. Einzelbäume fehlen, nur zusammenhängende
  Waldflächen aus OSM zählen. Das Horizontprofil hat 30°-Auflösung und wird
  zwischen den Richtungen interpoliert.
- Steigungswerte stammen aus einem ~30-m-Höhenmodell. Kurze Rampen können
  dadurch geglättet sein.
- **Wickelräume sind in OSM hier nirgends erfasst**, und die beiden einzigen
  WCs im Datensatz liegen rund 4 km südwestlich an keiner Runde. Solche Punkte
  muss man sich selbst setzen; sie bleiben im Browser des Geräts.
- Schattenzeiten gibt es nur für die Standardführung, nicht für Varianten.
- Rastpunkte und WCs stammen aus OpenStreetMap und sind dort unvollständig:
  im Umkreis von 1,5 km um den See ist kein WC verzeichnet, obwohl es am
  Bootshaus welche geben soll.
- Die Wegequalität hängt an den OSM-Tags. Wo `surface` fehlt, wird neutral
  bewertet — die Kinderwagen-Einstufung ist ein Anhaltspunkt, keine Garantie.

## Daten

Wege und Orte © OpenStreetMap-Mitwirkende (ODbL) · Luftbild © Esri, Maxar,
Earthstar Geographics · Höhendaten Mapzen/AWS Terrain Tiles ·
Bodenfotos © Panoramax-Mitwirkende (CC-BY-SA)

## Fremde Bibliotheken

| Bibliothek | Lizenz | wofür |
|---|---|---|
| [MapLibre GL JS](https://github.com/maplibre/maplibre-gl-js) | BSD-3-Clause | Kartendarstellung, Gelände |
| [maplibre-contour](https://github.com/onthegomap/maplibre-contour) | BSD-3-Clause | Höhenlinien im Browser, erst beim Einschalten geladen |

Beide Lizenzen sind mit der MIT-Lizenz dieses Projekts vereinbar. Routen-Motor,
Schattenberechnung, Sonnenstand und GPX-Export sind eigener Code — Anregungen
dafür kamen von [gpx.studio](https://github.com/gpxstudio/gpx.studio) (MIT) und
[Trail Planner](https://github.com/bogdandm/georgia-routing-planner), ohne Code
zu übernehmen.

## Lizenz

MIT
