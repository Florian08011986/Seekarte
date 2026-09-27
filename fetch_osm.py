import json, urllib.request, sys, os
LAT_MIN, LAT_MAX = 47.335, 47.392
LON_MIN, LON_MAX = 10.815, 10.885
OUT = "/data/data/com.termux/files/home/blindsee_3d/osm_cache.json"
query = f"""[out:json][timeout:90];
(
  way["highway"]({LAT_MIN},{LON_MIN},{LAT_MAX},{LON_MAX});
  way["natural"="water"]({LAT_MIN},{LON_MIN},{LAT_MAX},{LON_MAX});
  way["natural"="wood"]({LAT_MIN},{LON_MIN},{LAT_MAX},{LON_MAX});
  way["landuse"="forest"]({LAT_MIN},{LON_MIN},{LAT_MAX},{LON_MAX});
  node["tourism"]({LAT_MIN},{LON_MIN},{LAT_MAX},{LON_MAX});
  node["amenity"]({LAT_MIN},{LON_MIN},{LAT_MAX},{LON_MAX});
  node["natural"]({LAT_MIN},{LON_MIN},{LAT_MAX},{LON_MAX});
);
out body;
>;
out skel qt;"""
for host in ["https://lz4.overpass-api.de/api/interpreter",
             "https://overpass-api.de/api/interpreter",
             "https://overpass.kumi.systems/api/interpreter"]:
    try:
        req = urllib.request.Request(host, data=query.encode())
        req.add_header("User-Agent", "blindsee-map-build/2.0")
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.loads(r.read())
        json.dump(d, open(OUT, "w"))
        print(f"OK {host}: {len(d['elements'])} Elemente -> {OUT}")
        sys.exit(0)
    except Exception as e:
        print(f"FEHLER {host}: {type(e).__name__}: {e}")
sys.exit(1)
