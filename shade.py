"""
Schattenberechnung fuer die Blindsee-Runden.

Ob ein Punkt in der Sonne liegt, haengt an zwei Dingen: steht die Sonne hoch
genug ueber den umliegenden Bergen, und steht man unter Baeumen. Beides wird
hier vorbereitet, damit die Karte fuer jede Uhrzeit sofort antworten kann:

  1. Fuer Stuetzpunkte entlang jeder Runde wird aus dem Hoehenmodell ein
     Horizontprofil gerechnet - fuer 12 Himmelsrichtungen der Winkel, ab dem
     die Sonne ueber dem Gelaende steht.
  2. Dazu ein Wald-Flag aus den OSM-Flaechen.

Die Sonnenposition selbst rechnet die Karte im Browser, damit Datum und
Uhrzeit frei waehlbar bleiben.

Das Horizontprofil braucht ein weiteres Hoehenmodell als das Hoehenprofil
(Berge bis ~10 km wirken auf den Schatten). Es wird bei Bedarf aus
dem_N47_E010.tif geschnitten; ohne diese Kachel wird ein vorhandener
shade_cache.json weiterverwendet.
"""
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DEM_TIF = os.path.join(HERE, "dem_N47_E010.tif")
DEM_WIDE = os.path.join(HERE, "dem_horizon.asc")
CACHE = os.path.join(HERE, "shade_cache.json")

# Ausschnitt fuer das Horizontmodell (die Kachel endet bei 11.0 E)
H_LON_MIN, H_LON_MAX = 10.69, 10.9995
H_LAT_MIN, H_LAT_MAX = 47.25, 47.47

AZ_BINS = 12                  # Himmelsrichtungen alle 30 Grad
SAMPLE_M = 80.0               # Stuetzpunkt-Abstand entlang der Runde
RAY_MAX_M = 10000.0           # so weit wird nach Bergen gesucht
RAY_MIN_M = 30.0
EYE_M = 1.5


def load_wide_dem():
    """get_z(lat, lon) fuer den grossen Ausschnitt, oder None ohne Kachel."""
    if not os.path.exists(DEM_WIDE):
        if not os.path.exists(DEM_TIF):
            return None
        os.system(
            f"gdal_translate -q -of AAIGrid -projwin {H_LON_MIN} {H_LAT_MAX} "
            f"{H_LON_MAX} {H_LAT_MIN} {DEM_TIF} {DEM_WIDE}"
        )
    if not os.path.exists(DEM_WIDE):
        return None

    hdr = {}
    vals = []
    with open(DEM_WIDE) as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue
            probe = parts[0].replace(".", "").replace("-", "")
            if len(parts) == 2 and not probe.isdigit():
                hdr[parts[0].lower()] = float(parts[1])
            else:
                vals.extend(map(float, parts))

    ncols, nrows = int(hdr["ncols"]), int(hdr["nrows"])
    xll, yll, cell = hdr["xllcorner"], hdr["yllcorner"], hdr["cellsize"]
    top = yll + nrows * cell

    def get_z(lat, lon):
        c = int((lon - xll) / cell)
        r = int((top - lat) / cell)
        if c < 0 or r < 0 or c >= ncols or r >= nrows:
            return None
        return vals[r * ncols + c]

    return get_z


def horizon_profile(get_z, lat, lon, z0):
    """Fuer jede Himmelsrichtung der Winkel, ab dem die Sonne frei steht."""
    out = []
    coslat = math.cos(math.radians(lat))
    for b in range(AZ_BINS):
        az = math.radians(b * 360.0 / AZ_BINS)
        sin_a, cos_a = math.sin(az), math.cos(az)
        best = 0.0
        r = RAY_MIN_M
        while r <= RAY_MAX_M:
            plat = lat + (r * cos_a) / 110540.0
            plon = lon + (r * sin_a) / (111320.0 * coslat)
            z = get_z(plat, plon)
            if z is not None:
                ang = math.degrees(math.atan2(z - (z0 + EYE_M), r))
                if ang > best:
                    best = ang
            r += max(30.0, r * 0.03)   # nah fein, fern grob
        out.append(round(best, 1))
    return out


def point_in_ring(pt, ring):
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


def haversine(a, b):
    R = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = math.radians(b[0] - a[0])
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def sample_route(coords, step_m=SAMPLE_M):
    """Gleichmaessig verteilte Stuetzpunkte (lat, lon) entlang der Runde."""
    pts = [(c[1], c[0]) for c in coords]      # coords sind [lon, lat]
    out, carry = [pts[0]], 0.0
    for a, b in zip(pts, pts[1:]):
        d = haversine(a, b)
        if d == 0:
            continue
        carry += d
        while carry >= step_m:
            over = carry - step_m
            t = 1.0 - over / d
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            carry = over
    return out


def compute(routes, osm, verbose=False):
    """Haengt jeder Runde ihr Schattenmodell an. Nutzt den Cache wo moeglich."""
    cache = {}
    if os.path.exists(CACHE):
        try:
            cache = json.load(open(CACHE))
        except Exception:
            cache = {}

    get_z = None
    forests = osm.get("forests", [])
    changed = False

    for r in routes:
        key = f"{r['id']}:{len(r['coords'])}:{r['km']}"
        if key in cache:
            r["shade"] = cache[key]
            if verbose:
                print(f"[shade] {r['name']:20s} aus Cache "
                      f"({len(cache[key]['hz'])} Stützpunkte)")
            continue

        if get_z is None:
            get_z = load_wide_dem()
            if get_z is None:
                if verbose:
                    print("[shade] kein Höhenmodell und kein Cache — "
                          f"{r['name']} bleibt ohne Schattenzeiten")
                continue

        samples = sample_route(r["coords"])
        hz, forest_bits = [], []
        for (lat, lon) in samples:
            z0 = get_z(lat, lon)
            if z0 is None:
                z0 = 1100.0
            hz.append(horizon_profile(get_z, lat, lon, z0))
            in_wood = 0
            for (bbox, poly) in forests:
                if bbox[0] <= lat <= bbox[1] and bbox[2] <= lon <= bbox[3]:
                    if point_in_ring((lat, lon), poly):
                        in_wood = 1
                        break
            forest_bits.append(str(in_wood))

        r["shade"] = {"step_m": int(SAMPLE_M), "bins": AZ_BINS,
                      "hz": hz, "fr": "".join(forest_bits)}
        cache[key] = r["shade"]
        changed = True
        if verbose:
            flat = [a for prof in hz for a in prof]
            print(f"[shade] {r['name']:20s} {len(hz):3d} Stützpunkte  "
                  f"Horizont Ø {sum(flat)/len(flat):4.1f}°  max {max(flat):4.1f}°  "
                  f"Wald {forest_bits.count('1')*100//len(forest_bits):3d} %")

    if changed:
        # nur die aktuell gueltigen Eintraege behalten, sonst waechst der Cache
        # bei jeder Geometrieaenderung weiter an
        live = {f"{r['id']}:{len(r['coords'])}:{r['km']}" for r in routes}
        cache = {k: v for k, v in cache.items() if k in live}
        json.dump(cache, open(CACHE, "w"), separators=(",", ":"))
        if verbose:
            print(f"[shade] Cache geschrieben: {os.path.getsize(CACHE)/1024:.0f} KB")
    return routes


if __name__ == "__main__":
    import route_engine
    hs = json.load(open(os.path.join(HERE, "hotspots.json"), encoding="utf-8"))
    rts = route_engine.build_routes(hs)
    compute(rts, route_engine.load_osm(), verbose=True)
