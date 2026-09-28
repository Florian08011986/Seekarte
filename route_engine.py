"""
Routen-Motor fuer die Blindsee-Karte.

Findet ECHTE Rundwege im OSM-Wegenetz statt erfundener Koordinatenlisten:
  1. Wegenetz als Graph aufbauen (Knoten ueber gemeinsame OSM-Node-IDs verbunden)
  2. Grad-2-Ketten zu Super-Kanten kontrahieren -> kleiner Kreuzungsgraph
  3. Fundamentalzyklen ueber Spannbaum bestimmen
  4. Benachbarte Zyklen per XOR zu groesseren Ringen kombinieren
  5. Pro Laengenklasse den kompaktesten seenahen Ring waehlen
  6. Jede Runde mit echten Kennzahlen anreichern (Hoehenmeter aus DEM, Steigung,
     Belag, Treppen, Schattenanteil, Uferanteil, angebundene Hotspots)

Alle ausgegebenen Kilometer-, Hoehenmeter- und Steigungswerte sind aus der
Geometrie gerechnet, nicht hartkodiert.
"""
import json
import math
import os
import collections

HERE = os.path.dirname(os.path.abspath(__file__))
OSM_CACHE = os.path.join(HERE, "osm_cache.json")
DEM_ASC = os.path.join(HERE, "dem_wide.asc")
DEM_TIF = os.path.join(HERE, "dem_N47_E010.tif")

# Ausschnitt fuer DEM und Overpass
LAT_MIN, LAT_MAX = 47.335, 47.392
LON_MIN, LON_MAX = 10.815, 10.885

# Wege auf denen man zu Fuss unterwegs sein kann
WALKABLE = {
    "path", "footway", "track", "pedestrian", "steps", "cycleway",
    "bridleway", "residential", "service", "unclassified", "living_street",
}
# Belag der als kinderwagentauglich durchgeht
GOOD_SURFACE = {"asphalt", "paved", "concrete", "compacted", "fine_gravel", "gravel"}

LOOP_BANDS = [
    # (min_km, max_km, id, Anzeigename)
    (1.0, 1.8, "mini", "Kleine Uferrunde"),
    (1.8, 2.8, "kurz", "Kurze Waldrunde"),
    (2.8, 4.2, "see", "Seeumrundung"),
    (4.2, 6.2, "gross", "Grosse Runde"),
    (6.2, 11.0, "pano", "Panorama-Runde"),
]


# ---------------------------------------------------------------- Geometrie

def haversine(a, b):
    """Distanz in Metern zwischen zwei (lat, lon)-Tupeln."""
    R = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dphi = math.radians(b[0] - a[0])
    dlam = math.radians(b[1] - a[1])
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def point_in_ring(pt, ring):
    """Ray-Casting auf einem Ring aus (lat, lon)-Tupeln."""
    y, x = pt
    inside = False
    n = len(ring)
    for i in range(n):
        y1, x1 = ring[i]
        y2, x2 = ring[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xin = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < xin:
                inside = not inside
    return inside


def dist_to_polyline(pt, line):
    """Kuerzester Abstand (m) von pt zu einer Polylinie aus (lat, lon)."""
    best = float("inf")
    lat0 = pt[0]
    kx = 111320.0 * math.cos(math.radians(lat0))
    ky = 110540.0
    px, py = pt[1] * kx, pt[0] * ky
    for a, b in zip(line, line[1:]):
        ax, ay = a[1] * kx, a[0] * ky
        bx, by = b[1] * kx, b[0] * ky
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        if L2 == 0:
            d = math.hypot(px - ax, py - ay)
        else:
            t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
            d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
        if d < best:
            best = d
    return best


# ---------------------------------------------------------------- Hoehendaten

def load_dem():
    """Liefert get_z(lat, lon) -> Meter ueber NN aus dem ASCII-Grid."""
    if not os.path.exists(DEM_ASC):
        os.system(
            f"gdal_translate -q -of AAIGrid -projwin {LON_MIN} {LAT_MAX} "
            f"{LON_MAX} {LAT_MIN} {DEM_TIF} {DEM_ASC}"
        )
    hdr = {}
    values = []
    with open(DEM_ASC) as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue
            first = parts[0].replace(".", "").replace("-", "")
            if len(parts) == 2 and not first.isdigit():
                hdr[parts[0].lower()] = float(parts[1])
            else:
                values.extend(float(v) for v in parts)

    ncols = int(hdr["ncols"])
    nrows = int(hdr["nrows"])
    xll = hdr["xllcorner"]
    yll = hdr["yllcorner"]
    cell = hdr["cellsize"]
    nodata = hdr.get("nodata_value", -9999.0)

    def sample(r, c):
        r = min(nrows - 1, max(0, r))
        c = min(ncols - 1, max(0, c))
        return values[r * ncols + c]

    def get_z(lat, lon):
        # Bilineare Interpolation: das Raster ist ~30 m grob, die Wegpunkte
        # liegen deutlich dichter. Ohne Interpolation springt die Hoehe
        # treppenfoermig und erzeugt Steigungen, die es nicht gibt.
        col = (lon - xll) / cell - 0.5
        row = (yll + nrows * cell - lat) / cell - 0.5
        c0, r0 = int(math.floor(col)), int(math.floor(row))
        fc, fr = col - c0, row - r0
        z00, z10 = sample(r0, c0), sample(r0, c0 + 1)
        z01, z11 = sample(r0 + 1, c0), sample(r0 + 1, c0 + 1)
        if nodata in (z00, z10, z01, z11):
            return None
        top = z00 * (1 - fc) + z10 * fc
        bot = z01 * (1 - fc) + z11 * fc
        return top * (1 - fr) + bot * fr

    return get_z


# ---------------------------------------------------------------- OSM laden

def build_lake_grid(lake_ring, pad_deg=0.006, cell_deg=0.00012):
    """
    Vorberechnetes Raster 'Abstand zum Seeufer'.

    Die Uferdistanz wird fuer jede Runde und jeden Punkt gebraucht; direkt gegen
    die 3,7-km-Uferlinie zu rechnen waere bei tausenden Kandidatenringen zu
    langsam. Das Raster deckt nur die Seeumgebung ab - ausserhalb gilt pauschal
    'weit weg'.
    """
    if not lake_ring:
        return None
    closed = lake_ring + [lake_ring[0]]
    lat0 = min(p[0] for p in closed) - pad_deg
    lat1 = max(p[0] for p in closed) + pad_deg
    lon0 = min(p[1] for p in closed) - pad_deg
    lon1 = max(p[1] for p in closed) + pad_deg
    nrows = int((lat1 - lat0) / cell_deg) + 1
    ncols = int((lon1 - lon0) / cell_deg) + 1
    grid = [0.0] * (nrows * ncols)
    for r in range(nrows):
        lat = lat0 + r * cell_deg
        for c in range(ncols):
            lon = lon0 + c * cell_deg
            grid[r * ncols + c] = dist_to_polyline((lat, lon), closed)
    return {
        "lat0": lat0, "lon0": lon0, "cell": cell_deg,
        "nrows": nrows, "ncols": ncols, "grid": grid,
    }


def lake_distance(grid, lat, lon):
    """Abstand zum Seeufer in Metern (999999 ausserhalb des Rasters)."""
    if grid is None:
        return 999999.0
    r = int((lat - grid["lat0"]) / grid["cell"])
    c = int((lon - grid["lon0"]) / grid["cell"])
    if r < 0 or c < 0 or r >= grid["nrows"] or c >= grid["ncols"]:
        return 999999.0
    return grid["grid"][r * grid["ncols"] + c]


def load_osm():
    data = json.load(open(OSM_CACHE))
    els = data["elements"]

    nodes = {e["id"]: (e["lat"], e["lon"]) for e in els if e["type"] == "node"}
    ways = [e for e in els if e["type"] == "way"]

    adj = collections.defaultdict(set)
    edge_tags = {}
    for w in ways:
        tags = w.get("tags", {})
        if tags.get("highway") not in WALKABLE:
            continue
        ns = [n for n in w["nodes"] if n in nodes]
        for a, b in zip(ns, ns[1:]):
            if a == b:
                continue
            adj[a].add(b)
            adj[b].add(a)
            edge_tags[frozenset((a, b))] = tags

    # See (groesste Wasserflaeche)
    lake = None
    for w in ways:
        if w.get("tags", {}).get("natural") != "water":
            continue
        ring = [nodes[n] for n in w["nodes"] if n in nodes]
        if len(ring) < 4:
            continue
        span = max(p[0] for p in ring) - min(p[0] for p in ring)
        if lake is None or span > lake[0]:
            lake = (span, w.get("tags", {}).get("name", "See"), ring)
    lake_ring = lake[2] if lake else []
    lake_name = lake[1] if lake else "See"
    if lake_ring:
        lake_center = (
            sum(p[0] for p in lake_ring) / len(lake_ring),
            sum(p[1] for p in lake_ring) / len(lake_ring),
        )
    else:
        lake_center = (47.36269, 10.84931)

    # Rast- und Versorgungspunkte. Fuer einen Ausflug mit Kinderwagen sind
    # Baenke die eigentliche Planungsgroesse - davon gibt es rund um den See
    # deutlich mehr als markierte Sehenswuerdigkeiten.
    POI_KINDS = {
        ("amenity", "bench"):          ("bench", "Bank"),
        ("amenity", "waste_basket"):   ("waste", "Abfalleimer"),
        ("amenity", "toilets"):        ("wc", "WC"),
        ("amenity", "drinking_water"): ("water", "Trinkwasser"),
        ("amenity", "shelter"):        ("shelter", "Unterstand"),
        ("amenity", "parking"):        ("parking", "Parkplatz"),
        ("amenity", "restaurant"):     ("food", "Einkehr"),
        ("tourism", "picnic_site"):    ("picnic", "Rastplatz"),
        ("tourism", "viewpoint"):      ("view", "Aussichtspunkt"),
        ("leisure", "picnic_table"):   ("picnic", "Rastplatz"),
    }
    pois = []
    for e in els:
        if e["type"] != "node":
            continue
        tags = e.get("tags") or {}
        for (k, v), (kind, label) in POI_KINDS.items():
            if tags.get(k) == v:
                pois.append({"kind": kind, "label": label,
                             "name": tags.get("name") or label,
                             "lat": e["lat"], "lon": e["lon"]})
                break

    # Waldflaechen fuer den Schattenanteil
    forests = []
    for w in ways:
        tags = w.get("tags", {})
        if tags.get("natural") == "wood" or tags.get("landuse") == "forest":
            ring = [nodes[n] for n in w["nodes"] if n in nodes]
            if len(ring) >= 4:
                lats = [p[0] for p in ring]
                lons = [p[1] for p in ring]
                forests.append(((min(lats), max(lats), min(lons), max(lons)), ring))

    return {
        "nodes": nodes,
        "adj": adj,
        "edge_tags": edge_tags,
        "lake_ring": lake_ring,
        "lake_name": lake_name,
        "lake_center": lake_center,
        "lake_grid": build_lake_grid(lake_ring),
        "pois": pois,
        "forests": forests,
    }


# ---------------------------------------------------------------- Graph

def contract(nodes, adj, edge_tags):
    """Grad-2-Ketten zu Super-Kanten zusammenfassen."""
    junctions = {n for n in adj if len(adj[n]) != 2}
    if not junctions:
        junctions = {next(iter(adj))}

    segs = []
    walked = set()
    for j in junctions:
        for nb in adj[j]:
            if (j, nb) in walked:
                continue
            path = [j, nb]
            walked.add((j, nb))
            prev, cur = j, nb
            while cur not in junctions:
                nxt = [x for x in adj[cur] if x != prev]
                if not nxt:
                    break
                prev, cur = cur, nxt[0]
                path.append(cur)
            walked.add((path[-1], path[-2]))
            length = sum(haversine(nodes[a], nodes[b]) for a, b in zip(path, path[1:]))
            tags = edge_tags.get(frozenset((path[0], path[1])), {})
            segs.append({
                "u": path[0], "v": path[-1], "path": path,
                "len": length, "tags": tags,
            })
    return junctions, segs


def largest_component(segs):
    a = collections.defaultdict(set)
    for s in segs:
        a[s["u"]].add(s["v"])
        a[s["v"]].add(s["u"])
    seen, best = set(), set()
    for n in a:
        if n in seen:
            continue
        stack, comp = [n], set()
        while stack:
            x = stack.pop()
            if x in comp:
                continue
            comp.add(x)
            seen.add(x)
            stack.extend(a[x] - comp)
        if len(comp) > len(best):
            best = comp
    return best


def cycle_basis(segs, comp):
    """Fundamentalzyklen als frozenset von Segment-Indizes."""
    a = collections.defaultdict(list)
    for i, s in enumerate(segs):
        if s["u"] in comp and s["v"] in comp:
            a[s["u"]].append((s["v"], i))
            a[s["v"]].append((s["u"], i))

    parent, pedge, tree = {}, {}, set()
    root = next(iter(comp))
    parent[root] = None
    stack, seen = [root], {root}
    while stack:
        x = stack.pop()
        for y, i in a[x]:
            if y not in seen:
                seen.add(y)
                parent[y] = x
                pedge[y] = i
                tree.add(i)
                stack.append(y)

    def to_root(n):
        out = []
        while parent.get(n) is not None:
            out.append(pedge[n])
            n = parent[n]
        return set(out)

    cycles = []
    for i, s in enumerate(segs):
        if i in tree or s["u"] not in seen or s["v"] not in seen:
            continue
        cycles.append(frozenset((to_root(s["u"]) ^ to_root(s["v"])) | {i}))
    return cycles


def ring_nodes(segs, edgeset):
    """Prueft ob die Kantenmenge EIN einfacher Ring ist -> geordnete Knotenfolge."""
    deg = collections.defaultdict(int)
    a = collections.defaultdict(list)
    for i in edgeset:
        s = segs[i]
        deg[s["u"]] += 1
        deg[s["v"]] += 1
        a[s["u"]].append((s["v"], i))
        a[s["v"]].append((s["u"], i))
    if not deg or any(d != 2 for d in deg.values()):
        return None

    start = next(iter(deg))
    out, used, cur = [], set(), start
    while True:
        nxt = next(((v, i) for v, i in a[cur] if i not in used), None)
        if nxt is None:
            break
        v, i = nxt
        used.add(i)
        s = segs[i]
        p = s["path"] if s["u"] == cur else list(reversed(s["path"]))
        out.extend(p[:-1])
        cur = v
        if cur == start:
            break
    if len(used) != len(edgeset) or cur != start:
        return None  # zerfaellt in mehrere Ringe
    out.append(start)
    return out


def ring_shape(nodes, ring):
    """Laenge, Flaeche und isoperimetrischer Quotient (1.0 = Kreis)."""
    pts = [nodes[n] for n in ring]
    length = sum(haversine(a, b) for a, b in zip(pts, pts[1:]))
    clat = sum(p[0] for p in pts) / len(pts)
    clon = sum(p[1] for p in pts) / len(pts)
    kx = 111320.0 * math.cos(math.radians(clat))
    ky = 110540.0
    xy = [((p[1] - clon) * kx, (p[0] - clat) * ky) for p in pts]
    area = abs(sum(xy[i][0] * xy[i + 1][1] - xy[i + 1][0] * xy[i][1]
                   for i in range(len(xy) - 1)) / 2)
    iq = 4 * math.pi * area / (length * length) if length > 0 else 0.0
    return length, area, iq, (clat, clon)


# ---------------------------------------------------------------- Loop-Suche

def find_loops(osm, max_depth=8, frontier_cap=12000):
    nodes, adj, edge_tags = osm["nodes"], osm["adj"], osm["edge_tags"]
    lake_center = osm["lake_center"]

    junctions, segs = contract(nodes, adj, edge_tags)
    comp = largest_component(segs)
    base = cycle_basis(segs, comp)

    simple = {}
    for c in base:
        r = ring_nodes(segs, c)
        if r:
            simple[c] = r

    neighbours = collections.defaultdict(set)
    keys = list(simple)
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            if keys[i] & keys[j]:
                neighbours[keys[i]].add(keys[j])
                neighbours[keys[j]].add(keys[i])

    grid = osm.get("lake_grid")

    def near_lake(ring):
        return min(haversine(nodes[n], lake_center) for n in ring)

    def shore_share(ring):
        """Anteil der Ringpunkte innerhalb 120 m vom Ufer."""
        hit = sum(1 for n in ring
                  if lake_distance(grid, nodes[n][0], nodes[n][1]) < 120)
        return hit / len(ring) if ring else 0.0

    seeds = [c for c in simple if near_lake(simple[c]) < 900]
    found = {}
    frontier = [(frozenset(s), {s}) for s in seeds]

    for _ in range(max_depth):
        nxt = []
        for edges, used in frontier:
            ring = ring_nodes(segs, edges)
            if ring:
                length, area, iq, centre = ring_shape(nodes, ring)
                dmin = near_lake(ring)
                if 900 <= length <= 11500 and iq > 0.12 and dmin < 700:
                    if edges not in found:
                        found[edges] = (length, iq, dmin, ring, shore_share(ring))
            pool = set().union(*(neighbours[u] for u in used)) if used else set()
            for nb in pool - used:
                merged = edges ^ nb
                if merged:
                    nxt.append((merged, used | {nb}))
        dedup, seen = [], set()
        for e, u in nxt:
            if e in seen:
                continue
            seen.add(e)
            dedup.append((e, u))
        frontier = dedup[:frontier_cap]
        if not frontier:
            break

    return segs, found


def pick_per_band(osm, found, variants=3):
    """
    Pro Laengenklasse die besten Ringe.

    Der erste ist der Vorschlag, die weiteren sind echte Alternativen mit
    anderer Streckenfuehrung - dafuer muessen sie sich deutlich vom bereits
    Gewaehlten unterscheiden, sonst bekommt man dreimal fast dasselbe.
    """
    ranked = collections.defaultdict(list)
    for length, iq, dmin, ring, shore in found.values():
        km = length / 1000.0
        for lo, hi, rid, name in LOOP_BANDS:
            if lo <= km < hi:
                # Kompakte Form UND Naehe zum Wasser - beides macht eine Runde
                # erst zu einer, die man auch gehen will.
                score = 0.5 * iq + 0.5 * shore - dmin / 40000.0
                ranked[rid].append((score, length, iq, dmin, ring, name, shore))

    best = {}
    for rid, items in ranked.items():
        items.sort(key=lambda x: -x[0])
        chosen = []
        for it in items:
            nodes_set = set(it[4])
            if all(len(nodes_set & set(c[4])) / max(1, min(len(nodes_set), len(c[4]))) < 0.65
                   for c in chosen):
                chosen.append(it)
            if len(chosen) >= variants:
                break
        best[rid] = chosen[0] + (chosen[1:],)
    return best


# ---------------------------------------------------------------- Kennzahlen

def enrich(osm, get_z, ring, hotspots):
    """Berechnet die echten Kennzahlen einer Runde."""
    nodes = osm["nodes"]
    pts = [nodes[n] for n in ring]

    # Hoehenprofil glaetten, damit DEM-Rauschen keine Fantasie-Hoehenmeter macht
    raw = [get_z(p[0], p[1]) for p in pts]
    zs, last = [], None
    for z in raw:
        if z is None:
            z = last if last is not None else 1100.0
        last = z
        zs.append(z)
    win = 5
    smooth = [
        sum(zs[max(0, i - win): min(len(zs), i + win + 1)])
        / len(zs[max(0, i - win): min(len(zs), i + win + 1)])
        for i in range(len(zs))
    ]

    seg_lengths = [haversine(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    total = sum(seg_lengths)

    # Das DEM hat ~30 m Rasterweite, die Wegpunkte liegen oft nur 5 m auseinander.
    # Direkt Punkt-zu-Punkt gerechnet ergaebe das Fantasie-Steigungen von 40 %+.
    # Deshalb das Hoehenprofil auf feste Schritte resampeln und darauf rechnen.
    STEP = 50.0
    cum = [0.0]
    for d in seg_lengths:
        cum.append(cum[-1] + d)

    def z_at(dist):
        if dist <= 0:
            return smooth[0]
        if dist >= cum[-1]:
            return smooth[-1]
        lo, hi = 0, len(cum) - 1
        while lo < hi - 1:
            mid = (lo + hi) // 2
            if cum[mid] <= dist:
                lo = mid
            else:
                hi = mid
        span = cum[hi] - cum[lo]
        t = (dist - cum[lo]) / span if span > 0 else 0.0
        return smooth[lo] + t * (smooth[hi] - smooth[lo])

    n_steps = max(2, int(total // STEP))
    prof = [z_at(i * total / n_steps) for i in range(n_steps + 1)]

    ascent = descent = 0.0
    max_slope = 0.0
    seg_d = total / n_steps
    steep = 0
    slopes = []
    for i in range(len(prof) - 1):
        dz = prof[i + 1] - prof[i]
        if dz > 0:
            ascent += dz
        else:
            descent -= dz
        sl = abs(dz) / seg_d * 100.0
        slopes.append(sl)
        max_slope = max(max_slope, sl)
        if sl > 12.0:
            steep += 1
    # Anteil der Strecke der wirklich steil ist. Eine einzelne kurze Rampe
    # darf eine sonst flache Runde nicht disqualifizieren - der Maximalwert
    # allein waere dafuer ein zu grobes Mass.
    steep_share = steep / len(slopes) if slopes else 0.0

    # Belag / Treppen aus den OSM-Tags der beteiligten Kanten
    edge_tags = osm["edge_tags"]
    good = bad = 0.0
    steps_m = 0.0
    steps_at = []
    for i in range(len(ring) - 1):
        tags = edge_tags.get(frozenset((ring[i], ring[i + 1])), {})
        d = seg_lengths[i] if i < len(seg_lengths) else 0
        if tags.get("highway") == "steps":
            steps_m += d
            # Position merken: mit Kinderwagen ist entscheidend, WO getragen
            # werden muss, nicht nur dass es Treppen gibt.
            if steps_at and cum[i] - steps_at[-1]["to_m"] < 30:
                steps_at[-1]["to_m"] = cum[i] + d
            else:
                steps_at.append({"at_m": cum[i], "to_m": cum[i] + d})
        surface = tags.get("surface")
        tracktype = tags.get("tracktype")
        if surface in GOOD_SURFACE or tracktype in ("grade1", "grade2"):
            good += d
        elif surface or tracktype:
            bad += d
    known = good + bad
    surface_quality = (good / known) if known > 0 else 0.5

    # Uferanteil
    grid = osm.get("lake_grid")
    near_water = 0.0
    for i, p in enumerate(pts[:-1]):
        if lake_distance(grid, p[0], p[1]) < 120:
            near_water += seg_lengths[i]
    lake_share = near_water / total if total else 0.0

    # Schattenanteil (Waldflaechen)
    shaded = 0.0
    for i, p in enumerate(pts[:-1]):
        for (bbox, poly) in osm["forests"]:
            if bbox[0] <= p[0] <= bbox[1] and bbox[2] <= p[1] <= bbox[3]:
                if point_in_ring(p, poly):
                    shaded += seg_lengths[i]
                    break
    shade_share = shaded / total if total else 0.0

    # Steile Abschnitte zusammenhaengend erfassen: mit Kinderwagen zaehlt
    # nicht der Spitzenwert, sondern wo und wie lang geschoben werden muss.
    steep_sections = []
    run_start = None
    for i, sl in enumerate(slopes):
        if sl > 10.0 and run_start is None:
            run_start = i
        elif sl <= 10.0 and run_start is not None:
            length = (i - run_start) * seg_d
            if length >= 40:
                steep_sections.append({
                    "at_km": round(run_start * seg_d / 1000.0, 2),
                    "length_m": int(round(length)),
                    "slope_pct": round(max(slopes[run_start:i]), 1),
                })
            run_start = None
    if run_start is not None:
        length = (len(slopes) - run_start) * seg_d
        if length >= 40:
            steep_sections.append({
                "at_km": round(run_start * seg_d / 1000.0, 2),
                "length_m": int(round(length)),
                "slope_pct": round(max(slopes[run_start:]), 1),
            })

    # Rastpunkte entlang der Runde, mit Position ab Start
    rest = []
    for poi in osm.get("pois", []):
        best_d, best_at = float("inf"), 0.0
        for i, p in enumerate(pts[:-1]):
            dd = haversine((poi["lat"], poi["lon"]), p)
            if dd < best_d:
                best_d, best_at = dd, cum[i]
        if best_d <= 45:
            rest.append({
                "kind": poi["kind"], "label": poi["label"], "name": poi["name"],
                "lat": round(poi["lat"], 6), "lon": round(poi["lon"], 6),
                "at_km": round(best_at / 1000.0, 2), "off_m": int(round(best_d)),
            })
    rest.sort(key=lambda r: r["at_km"])

    # Angebundene Hotspots
    on_route = []
    for hs in hotspots:
        d = dist_to_polyline((hs["lat"], hs["lon"]), pts)
        if d < 160:
            on_route.append({"id": hs["id"], "detour_m": round(d)})
    on_route.sort(key=lambda h: h["detour_m"])

    # Kinderwagen-Ampel statt Ja/Nein: die schoenste Runde am Ufer faellt sonst
    # allein wegen naturbelassenem Untergrund durch, obwohl sie mit einem
    # gelaendegaengigen Wagen gut machbar ist. Die Ampel sagt, WAS einen erwartet.
    push_m = sum(x["length_m"] for x in steep_sections)
    hard_push = [x for x in steep_sections if x["slope_pct"] > 15 and x["length_m"] > 120]
    stroller_notes = []
    if steps_m >= 1:
        stroller_grade = "red"
        where = ", ".join(f"km {x['at_m']/1000:.1f}".replace(".", ",") for x in steps_at)
        stroller_notes.append(
            f"{int(steps_m)} m Treppen ({where}) — Wagen muss getragen werden")
    elif steep_share > 0.18 or hard_push:
        stroller_grade = "red"
        stroller_notes.append("zu lange steile Abschnitte zum Schieben")
    elif surface_quality > 0.70 and steep_share < 0.06:
        stroller_grade = "green"
        if steep_sections:
            n = len(steep_sections)
            stroller_notes.append(
                f"befestigter Untergrund, keine Stufen — "
                f"{n} kurze Rampe{'n' if n != 1 else ''} ({push_m} m), sonst flach")
        else:
            stroller_notes.append("befestigter Untergrund, keine Stufen, durchgehend flach")
    else:
        stroller_grade = "yellow"
        if surface_quality <= 0.70:
            stroller_notes.append("naturbelassener Weg — geländegängiger Wagen sinnvoll")
        if push_m > 0:
            stroller_notes.append(
                f"{len(steep_sections)} Stelle{'n' if len(steep_sections) != 1 else ''} "
                f"zum Schieben, zusammen {push_m} m")
    stroller_ok = stroller_grade == "green"
    dog_ok = steps_m < 40

    # Gehzeit nach DIN 33466 / SAC: 4 km/h horizontal, 300 Hm/h Aufstieg
    hours = total / 4000.0 + ascent / 300.0
    minutes = int(round(hours * 60))

    return {
        "km": round(total / 1000.0, 2),
        "ascent_m": int(round(ascent)),
        "descent_m": int(round(descent)),
        "max_slope_pct": round(max_slope, 1),
        "steep_share": round(steep_share, 2),
        "steps_m": int(round(steps_m)),
        "steps_at": [{"at_km": round(x["at_m"] / 1000.0, 2),
                      "length_m": int(round(x["to_m"] - x["at_m"]))} for x in steps_at],
        "surface_quality": round(surface_quality, 2),
        "lake_share": round(lake_share, 2),
        "shade_share": round(shade_share, 2),
        "stroller_ok": stroller_ok,
        "dog_ok": dog_ok,
        "minutes": minutes,
        "duration": f"{minutes // 60}h {minutes % 60:02d}m" if minutes >= 60 else f"{minutes} Min",
        "highpoint_m": int(round(max(smooth))),
        "lowpoint_m": int(round(min(smooth))),
        "profile": [round(prof[i * len(prof) // 60 if len(prof) > 60 else i], 1)
                    for i in range(min(60, len(prof)))],
        "stroller_grade": stroller_grade,
        "stroller_notes": stroller_notes,
        "push_m": push_m,
        "steep_sections": steep_sections,
        "rest_points": rest,
        "benches": sum(1 for r in rest if r["kind"] == "bench"),
        "hotspots": [h["id"] for h in on_route],
        "hotspot_detours": {h["id"]: h["detour_m"] for h in on_route},
        "coords": [[round(p[1], 5), round(p[0], 5)] for p in simplify(pts)],
    }


def simplify(points, tol_m=3.0):
    """Douglas-Peucker: entfernt Punkte, die auf der Linie ohnehin liegen."""
    if len(points) < 3:
        return points
    lat0 = points[0][0]
    kx = 111320.0 * math.cos(math.radians(lat0))
    ky = 110540.0
    xy = [((p[1] * kx), (p[0] * ky)) for p in points]

    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        i, j = stack.pop()
        ax, ay = xy[i]
        bx, by = xy[j]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        worst, wi = 0.0, -1
        for k in range(i + 1, j):
            px, py = xy[k]
            if L2 == 0:
                d = math.hypot(px - ax, py - ay)
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
                d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
            if d > worst:
                worst, wi = d, k
        if wi >= 0 and worst > tol_m:
            keep[wi] = True
            stack.append((i, wi))
            stack.append((wi, j))
    return [p for p, k in zip(points, keep) if k]


def difficulty(stats):
    if stats["stroller_ok"] and stats["km"] <= 3.0:
        return "Leicht"
    if stats["ascent_m"] < 120 and stats["max_slope_pct"] < 14:
        return "Leicht"
    if stats["ascent_m"] < 320 and stats["max_slope_pct"] < 22:
        return "Mittel"
    return "Sportlich"


def dijkstra_from(nodes, adj, sources, targets, max_m=1200.0):
    """
    Kuerzeste Wege von einer Menge Startknoten zu mehreren Zielen.

    Wird fuer Abstecher gebraucht: von der Runde weg zu einem Punkt, der
    nicht direkt am Weg liegt - und zwar ueber echte Wege, nicht Luftlinie.
    """
    import heapq
    dist = {s: 0.0 for s in sources}
    prev = {}
    heap = [(0.0, s) for s in sources]
    heapq.heapify(heap)
    want = set(targets)
    found = {}
    while heap:
        d, u = heapq.heappop(heap)
        if d > dist.get(u, float("inf")):
            continue
        if u in want:
            found[u] = d
            want.discard(u)
            if not want:
                break
        if d > max_m:
            continue
        for v in adj[u]:
            nd = d + haversine(nodes[u], nodes[v])
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                prev[v] = u
                heapq.heappush(heap, (nd, v))
    return dist, prev, found


def nearest_node(nodes, adj, lat, lon, max_m=120.0):
    best, bd = None, max_m
    for n in adj:
        d = haversine(nodes[n], (lat, lon))
        if d < bd:
            bd, best = d, n
    return best


def build_spurs(osm, ring, pois, verbose=False):
    """Abstecher von der Runde zu Punkten, die nicht direkt am Weg liegen."""
    nodes, adj = osm["nodes"], osm["adj"]
    on_route = set(ring)
    pts = [nodes[n] for n in ring]

    WORTH_A_DETOUR = {"wc", "water", "shelter", "picnic", "food", "view", "parking"}
    cands = []
    for poi in pois:
        if poi["kind"] not in WORTH_A_DETOUR:
            continue
        d_line = dist_to_polyline((poi["lat"], poi["lon"]), pts)
        if 45 < d_line <= 700:
            nn = nearest_node(nodes, adj, poi["lat"], poi["lon"])
            if nn is not None and nn not in on_route:
                cands.append((poi, nn))
    if not cands:
        return []

    dist, prev, found = dijkstra_from(nodes, adj, on_route, [c[1] for c in cands])
    spurs = []
    for poi, nn in cands:
        if nn not in found:
            continue
        path, cur = [nn], nn
        while cur in prev:
            cur = prev[cur]
            path.append(cur)
            if cur in on_route:
                break
        if path[-1] not in on_route:
            continue
        path.reverse()
        length = sum(haversine(nodes[a], nodes[b]) for a, b in zip(path, path[1:]))
        if length < 10 or length > 900:
            continue
        # Position des Abzweigs auf der Runde
        branch = path[0]
        at_m = 0.0
        acc = 0.0
        for i in range(len(ring) - 1):
            if ring[i] == branch:
                at_m = acc
                break
            acc += haversine(nodes[ring[i]], nodes[ring[i + 1]])
        spurs.append({
            "kind": poi["kind"], "label": poi["label"], "name": poi["name"],
            "lat": round(poi["lat"], 6), "lon": round(poi["lon"], 6),
            "at_km": round(at_m / 1000.0, 2),
            "detour_m": int(round(length * 2)),      # hin und zurueck
            "coords": [[round(nodes[n][1], 5), round(nodes[n][0], 5)] for n in path],
        })
    spurs.sort(key=lambda x: x["detour_m"])
    if verbose and spurs:
        print("      Abstecher: " + ", ".join(
            f"{x['label']} +{x['detour_m']} m" for x in spurs[:6]))
    return spurs[:8]


def build_routes(hotspots, verbose=False):
    """Hauptfunktion: liefert die fertige Routenliste fuer die Karte."""
    osm = load_osm()
    get_z = load_dem()
    segs, found = find_loops(osm)
    picked = pick_per_band(osm, found)
    if verbose:
        print(f"[route_engine] {len(found)} saubere seenahe Ringe gefunden")

    routes = []
    for lo, hi, rid, name in LOOP_BANDS:
        if rid not in picked:
            if verbose:
                print(f"[route_engine] {name}: kein echter Ring in {lo}-{hi} km")
            continue
        score, length, iq, dmin, ring, label, shore, alts = picked[rid]
        stats = enrich(osm, get_z, ring, hotspots)
        stats["spurs"] = build_spurs(osm, ring, osm.get("pois", []), verbose)
        stats.update({
            "id": rid,
            "name": label,
            "compactness": round(iq, 2),
            "difficulty": difficulty(stats),
        })
        # Alternative Streckenfuehrungen derselben Laengenklasse
        stats["variants"] = []
        for a in alts:
            v = enrich(osm, get_z, a[4], hotspots)
            stats["variants"].append({
                "km": v["km"], "ascent_m": v["ascent_m"], "duration": v["duration"],
                "lake_share": v["lake_share"], "shade_share": v["shade_share"],
                "stroller_grade": v["stroller_grade"], "benches": v["benches"],
                "hotspots": v["hotspots"], "coords": v["coords"],
                "steep_sections": v["steep_sections"], "steps_at": v["steps_at"],
                "rest_points": v["rest_points"], "stroller_notes": v["stroller_notes"],
                "max_slope_pct": v["max_slope_pct"], "minutes": v["minutes"],
                "profile": v["profile"], "highpoint_m": v["highpoint_m"],
                "lowpoint_m": v["lowpoint_m"], "difficulty": difficulty(v),
                "hotspot_detours": v["hotspot_detours"], "steep_share": v["steep_share"],
                "steps_m": v["steps_m"], "surface_quality": v["surface_quality"],
                "descent_m": v["descent_m"], "dog_ok": v["dog_ok"],
                "stroller_ok": v["stroller_ok"], "push_m": v["push_m"],
            })
        routes.append(stats)
        if verbose:
            print(
                f"[route_engine] {label:20s} {stats['km']:5.2f} km  "
                f"{stats['ascent_m']:4d} Hm  max {stats['max_slope_pct']:4.1f}%  "
                f"steil {stats['steep_share']:.2f}  "
            f"Belag {stats['surface_quality']:.2f}  Ufer {stats['lake_share']:.2f}  "
                f"Schatten {stats['shade_share']:.2f}  "
                f"Wagen:{stats['stroller_grade']:6s}  "
                f"Hotspots {len(stats['hotspots'])}  "
            f"Baenke {stats['benches']}  Schiebestellen {len(stats['steep_sections'])}  "
            f"Varianten {len(stats['variants'])}"
            )
    routes.sort(key=lambda r: r["km"])
    return routes


if __name__ == "__main__":
    demo = [
        {"id": "start", "lat": 47.3655, "lon": 10.8512},
        {"id": "ancient_pine", "lat": 47.3638, "lon": 10.8528},
        {"id": "viewpoint", "lat": 47.3622, "lon": 10.8431},
        {"id": "beach", "lat": 47.3590, "lon": 10.8480},
        {"id": "mountain_stream", "lat": 47.3582, "lon": 10.8450},
        {"id": "fisherman_bay", "lat": 47.3608, "lon": 10.8415},
        {"id": "sunken_forest", "lat": 47.3630, "lon": 10.8420},
        {"id": "cliff_path", "lat": 47.3648, "lon": 10.8438},
        {"id": "mudslide", "lat": 47.3660, "lon": 10.8485},
        {"id": "north_forest", "lat": 47.3645, "lon": 10.8450},
        {"id": "fernpass_pano", "lat": 47.3672, "lon": 10.8525},
    ]
    build_routes(demo, verbose=True)
