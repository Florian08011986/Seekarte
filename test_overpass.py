import urllib.request, json
query = """[out:json][timeout:25];
(
  way["highway"](47.355,10.84,47.37,10.86);
);
out body;
>;
out skel qt;"""
urls = ["https://lz4.overpass-api.de/api/interpreter", "https://z.overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
for url in urls:
    print(f"Trying {url}")
    try:
        req = urllib.request.Request(url, data=query.encode('utf-8'))
        req.add_header('User-Agent', 'Antigravity')
        with urllib.request.urlopen(req, timeout=10) as response:
            d = json.loads(response.read())
            print(f"Success! Found {len(d.get('elements', []))} elements.")
            break
    except Exception as e:
        print(e)
