import urllib.request, json
LAT_MIN, LAT_MAX = 47.355, 47.370
LON_MIN, LON_MAX = 10.840, 10.865
query = f"""[out:json][timeout:25];
(
  node["tourism"]({LAT_MIN},{LON_MIN},{LAT_MAX},{LON_MAX});
  node["amenity"]({LAT_MIN},{LON_MIN},{LAT_MAX},{LON_MAX});
  node["natural"="beach"]({LAT_MIN},{LON_MIN},{LAT_MAX},{LON_MAX});
  node["historic"]({LAT_MIN},{LON_MIN},{LAT_MAX},{LON_MAX});
  node["leisure"]({LAT_MIN},{LON_MIN},{LAT_MAX},{LON_MAX});
);
out body;"""
req = urllib.request.Request("https://lz4.overpass-api.de/api/interpreter", data=query.encode('utf-8'))
with urllib.request.urlopen(req) as response:
    data = json.loads(response.read())
    for el in data.get('elements', []):
        tags = el.get('tags', {})
        name = tags.get('name', 'Unknown')
        print(f"{{el['lat']}}, {{el['lon']}} - {{name}} - {{tags}}")
