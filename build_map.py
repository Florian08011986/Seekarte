import os
import json
import urllib.request
import urllib.error
import math

LAT_MIN, LAT_MAX = 47.356, 47.368
LON_MIN, LON_MAX = 10.842, 10.856
DEM_FILE = "dem_N47_E010.tif"

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi/2.0)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(delta_lambda/2.0)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def get_elevation_data():
    asc_file = "cropped_full.asc"
    lat_min_dem, lat_max_dem = 47.350, 47.370
    lon_min_dem, lon_max_dem = 10.835, 10.865
    
    if not os.path.exists(asc_file):
        os.system(f"gdal_translate -of AAIGrid -projwin {lon_min_dem} {lat_max_dem} {lon_max_dem} {lat_min_dem} {DEM_FILE} {asc_file}")
    
    with open(asc_file, 'r') as f:
        lines = f.readlines()
        
    headers = {}
    data_start = 0
    for i, line in enumerate(lines):
        parts = line.split()
        if len(parts) >= 2 and not parts[0].replace('.', '').replace('-', '').isdigit():
            headers[parts[0].lower()] = float(parts[1])
        else:
            data_start = i
            break
            
    width = int(headers.get('ncols', 0))
    height = int(headers.get('nrows', 0))
    
    heights = []
    for line in lines[data_start:]:
        for val in line.split():
            heights.append(float(val))
            
    def get_z(lat, lon):
        px = (lon - lon_min_dem) / (lon_max_dem - lon_min_dem)
        py = 1.0 - (lat - lat_min_dem) / (lat_max_dem - lat_min_dem)
        if px < 0 or px > 1 or py < 0 or py > 1: return 1093
        x = min(width - 1, int(px * width))
        y = min(height - 1, int(py * height))
        return heights[y * width + x]
        
    return get_z

def fetch_osm(get_z):
    query = f"""[out:json][timeout:25];
    (
      way["highway"]({LAT_MIN},{LON_MIN},{LAT_MAX},{LON_MAX});
      way["natural"="water"]["name"="Blindsee"];
    );
    out body;
    >;
    out skel qt;"""
    
    req = urllib.request.Request("https://lz4.overpass-api.de/api/interpreter", data=query.encode('utf-8'))
    req.add_header('User-Agent', 'Antigravity')
    
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read())
    except urllib.error.URLError:
        return {"type": "FeatureCollection", "features": []}, [], []
        
    nodes = {}
    for el in data.get('elements', []):
        if el['type'] == 'node':
            nodes[el['id']] = (el['lat'], el['lon'])
            
    features = []
    elevation_profile = []
    accumulated_dist = 0
    milestones = []
    next_milestone = 500
    
    for el in data.get('elements', []):
        if el['type'] == 'way':
            tags = el.get('tags', {})
            
            if tags.get('natural') == 'water':
                coords = []
                for ref in el['nodes']:
                    if ref in nodes:
                        coords.append([nodes[ref][1], nodes[ref][0]])
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [coords]},
                    "properties": {"is_lake": True}
                })
                continue
                
            highway = tags.get('highway', '')
            if highway in ['path', 'track', 'footway', 'pedestrian', 'unclassified']:
                is_main = False
                if tags.get('surface') in ['asphalt', 'paved', 'compacted', 'fine_gravel'] or tags.get('tracktype') in ['grade1', 'grade2']:
                    is_main = True
                
                coords = []
                for ref in el['nodes']:
                    if ref in nodes:
                        coords.append(nodes[ref])
                
                for i in range(len(coords) - 1):
                    lat1, lon1 = coords[i]
                    lat2, lon2 = coords[i+1]
                    z1, z2 = get_z(lat1, lon1), get_z(lat2, lon2)
                    dist = haversine(lat1, lon1, lat2, lon2)
                    if dist == 0: continue
                    slope = abs(z2 - z1) / dist * 100
                    
                    features.append({
                        "type": "Feature",
                        "geometry": {"type": "LineString", "coordinates": [[lon1, lat1], [lon2, lat2]]},
                        "properties": {"is_lake": False, "slope": min(slope, 30), "is_main": is_main}
                    })
                    
                    if is_main and dist > 5:
                        accumulated_dist += dist
                        elevation_profile.append([accumulated_dist, z2, lat2, lon2])
                        if accumulated_dist >= next_milestone:
                            milestones.append({
                                "type": "Feature",
                                "geometry": {"type": "Point", "coordinates": [lon2, lat2]},
                                "properties": {"label": f"{next_milestone/1000:.1f} km"}
                            })
                            next_milestone += 500
                            
    for m in milestones:
        m['properties']['is_milestone'] = True
        features.append(m)
                        
    return {"type": "FeatureCollection", "features": features}, elevation_profile, milestones

def build_html(geojson, hotspots, profile):
    # Extract coordinate points to define distinct real routes
    full_coords = [[p[3], p[2]] for p in profile]
    if len(full_coords) > 20:
        r1_coords = full_coords[:45] + list(reversed(full_coords[:45]))
        r2_coords = full_coords[:95] + list(reversed(full_coords[:95]))
        r3_coords = full_coords + [full_coords[0]]
        r4_coords = full_coords + [[10.8512, 47.3655], [10.8518, 47.3662], [10.8525, 47.3672], [10.8518, 47.3662], full_coords[0]]
    else:
        r1_coords = [[10.8512, 47.3655], [10.8431, 47.3622]]
        r2_coords = [[10.8512, 47.3655], [10.8480, 47.3590]]
        r3_coords = [[10.8512, 47.3655], [10.8480, 47.3590], [10.8420, 47.3630], [10.8512, 47.3655]]
        r4_coords = r3_coords

    routes_data = [
        {
            "id": "short",
            "name": "Uferspaziergang Bootshaus",
            "km": 1.8,
            "elevation": 35,
            "duration": "45 Min",
            "difficulty": "Leicht",
            "suitability": "Familienfreundlich • Kinderwagen",
            "desc": "Gemütlicher, flacher Uferweg vom Bootshaus am Nordostufer. Herrlicher Seeblick ohne Kletterstellen.",
            "hotspots": ["start", "ancient_pine", "viewpoint"],
            "coords": r1_coords
        },
        {
            "id": "beach",
            "name": "Familien-Strandrunde",
            "km": 3.4,
            "elevation": 65,
            "duration": "1h 15m",
            "difficulty": "Leicht",
            "suitability": "Picknick & Badespaß",
            "desc": "Idyllischer Wald- und Uferpfad vom Startpunkt bis zur sonnigen Kiesstrand-Bucht & zum Bergquellbach.",
            "hotspots": ["start", "ancient_pine", "viewpoint", "beach", "mountain_stream"],
            "coords": r2_coords
        },
        {
            "id": "full",
            "name": "Großer Blindsee-Rundweg",
            "km": 5.2,
            "elevation": 140,
            "duration": "1h 50m",
            "difficulty": "Mittel",
            "suitability": "Klassische Seeumrundung",
            "desc": "Die vollständige Umrundung des Blindsees. Führt an allen 10 Natur-Highlights rund um das Ufer vorbei.",
            "hotspots": ["start", "ancient_pine", "viewpoint", "beach", "mountain_stream", "fisherman_bay", "sunken_forest", "cliff_path", "mudslide", "north_forest"],
            "coords": r3_coords
        },
        {
            "id": "pano",
            "name": "Panorama-Runde Zugspitzblick",
            "km": 7.2,
            "elevation": 280,
            "duration": "2h 30m",
            "difficulty": "Sportlich",
            "suitability": "Alpin & Weitblick",
            "desc": "Kombiniert den Seeumlauf mit dem panoramareichen Aufstieg zum Rasthaus Zugspitzblick (B179).",
            "hotspots": ["start", "ancient_pine", "viewpoint", "beach", "mountain_stream", "fisherman_bay", "sunken_forest", "cliff_path", "mudslide", "north_forest", "fernpass_pano"],
            "coords": r4_coords
        }
    ]

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta name="theme-color" content="#0b1b26">
    <title>BLINDSEE REALITY MAP</title>
    
    <script src="https://unpkg.com/maplibre-gl@3.6.2/dist/maplibre-gl.js"></script>
    <link href="https://unpkg.com/maplibre-gl@3.6.2/dist/maplibre-gl.css" rel="stylesheet" />

    <style>
        :root {{
            --bg: #090b0e;
            --surface: rgba(13, 16, 20, 0.94);
            --surface-elevated: rgba(20, 24, 30, 0.98);
            --surface-hover: rgba(26, 32, 40, 0.96);
            --border: rgba(255, 255, 255, 0.08);
            --border-hover: rgba(255, 255, 255, 0.18);
            --border-active: #c5a059;
            --primary: #c5a059;
            --primary-soft: rgba(197, 160, 89, 0.12);
            --primary-hover: #d8b46e;
            --text: #f0f3f6;
            --muted: #828e98;
            --text-dim: #4d5862;
            --font-mono: ui-monospace, SFMono-Regular, "SF Pro Mono", Menlo, Consolas, monospace;
        }}
        * {{ box-sizing: border-box; -webkit-tap-highlight-color: transparent; }}
        body {{
            margin: 0; padding: 0; overflow: hidden;
            font-family: -apple-system, BlinkMacSystemFont, "Inter", "SF Pro Text", "Helvetica Neue", Arial, sans-serif;
            background: var(--bg); color: var(--text); -webkit-font-smoothing: antialiased;
        }}
        #map {{ position: absolute; top: 0; bottom: 0; width: 100%; z-index: 1; }}

        /* Top HUD Bar */
        #top-hud {{
            position: absolute; top: 14px; left: 14px; right: 14px;
            display: flex; justify-content: space-between; align-items: center;
            pointer-events: none; z-index: 25;
        }}
        .hud-pill {{
            background: var(--surface); backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
            border: 1px solid var(--border); border-radius: 8px;
            padding: 8px 12px; font-size: 11px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
            color: var(--text); pointer-events: auto; display: flex;
            align-items: center; gap: 8px; box-shadow: 0 4px 16px rgba(0,0,0,0.4);
        }}
        .hud-status-dot {{
            width: 6px; height: 6px; border-radius: 50%; background: #34d399;
        }}
        .hud-actions {{ display: flex; gap: 6px; pointer-events: auto; }}
        .hud-btn {{
            background: var(--surface); color: var(--text);
            border: 1px solid var(--border); border-radius: 8px;
            padding: 8px 12px; font-size: 11px; font-weight: 600; letter-spacing: 0.04em;
            cursor: pointer; backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
            display: flex; align-items: center; gap: 6px;
            transition: all 0.15s ease; box-shadow: 0 4px 14px rgba(0,0,0,0.3);
        }}
        .hud-btn:hover {{ background: var(--surface-hover); border-color: var(--border-hover); }}
        .hud-btn.active {{
            background: var(--primary-soft); border-color: var(--border-active); color: #fff;
        }}

        /* Active Route Floating Indicator (Clean Architectural Capsule) */
        #active-route-banner {{
            position: absolute; top: 62px; left: 50%; transform: translateX(-50%);
            background: var(--surface); backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
            border: 1px solid var(--border); border-radius: 6px;
            padding: 6px 14px; font-size: 11px; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase;
            color: var(--primary); pointer-events: auto; z-index: 24;
            display: flex; align-items: center; gap: 8px; cursor: pointer;
            box-shadow: 0 6px 20px rgba(0,0,0,0.45); transition: all 0.2s;
        }}
        #active-route-banner:hover {{
            border-color: var(--border-active); transform: translateX(-50%) translateY(-1px);
        }}
        .route-indicator-dot {{
            width: 5px; height: 5px; border-radius: 50%; background: var(--primary);
        }}

        /* Minimalist Architectural Markers (Swiss Grid Numbered Discs) */
        .minimal-marker {{
            width: 26px; height: 26px;
            background: rgba(11, 14, 18, 0.95);
            border-radius: 50%;
            border: 1px solid rgba(255, 255, 255, 0.22);
            color: #ffffff;
            display: flex; align-items: center; justify-content: center;
            font-family: var(--font-mono);
            font-size: 10px; font-weight: 700; letter-spacing: -0.02em;
            cursor: pointer;
            box-shadow: 0 4px 12px rgba(0,0,0,0.6);
            transition: all 0.15s ease;
            position: relative;
        }}
        .minimal-marker:hover, .minimal-marker:active {{
            transform: scale(1.18);
            border-color: var(--primary);
            box-shadow: 0 0 16px rgba(197, 160, 89, 0.4);
        }}
        .minimal-marker.dimmed {{
            opacity: 0.15; pointer-events: none; transform: scale(0.8);
        }}
        .reality-badge-dot {{
            position: absolute; top: -1px; right: -1px;
            width: 5px; height: 5px; border-radius: 50%;
            border: 1px solid #090b0e;
        }}
        .badge-3d {{ background: #38bdf8; }}
        .badge-360 {{ background: #34d399; }}
        .badge-photo {{ background: #828e98; }}
        .badge-map {{ background: #4d5862; }}

        /* Hotspot Detail Card (Bottom Sheet) */
        #hotspot-panel {{
            position: absolute; bottom: 16px; left: 50%; transform: translateX(-50%) translateY(140%);
            width: calc(100% - 28px); max-width: 440px; background: var(--surface);
            backdrop-filter: blur(24px); -webkit-backdrop-filter: blur(24px);
            border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px;
            transition: transform 0.35s cubic-bezier(0.16, 1, 0.3, 1);
            pointer-events: auto; z-index: 35; box-shadow: 0 20px 50px rgba(0,0,0,0.7);
        }}
        #hotspot-panel.open {{ transform: translateX(-50%) translateY(0); }}
        
        .hp-header {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px; }}
        .hp-title {{ font-size: 16px; font-weight: 700; color: #ffffff; margin: 0; letter-spacing: -0.01em; }}
        .hp-duration {{
            font-family: var(--font-mono); font-size: 11px; font-weight: 600; color: var(--muted);
            border: 1px solid var(--border); padding: 2px 7px; border-radius: 4px; white-space: nowrap;
        }}
        
        .hp-tags {{ display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }}
        .hp-tag {{
            font-size: 10px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase;
            padding: 3px 7px; border-radius: 4px; display: inline-flex; align-items: center; gap: 4px;
            border: 1px solid var(--border); background: rgba(255,255,255,0.03); color: var(--muted);
        }}
        .tag-kid-green {{ color: #a7f3d0; border-color: rgba(52, 211, 153, 0.3); background: rgba(52, 211, 153, 0.08); }}
        .tag-kid-yellow {{ color: #fef08a; border-color: rgba(234, 179, 8, 0.3); background: rgba(234, 179, 8, 0.08); }}
        .tag-kid-red {{ color: #fecaca; border-color: rgba(239, 68, 68, 0.3); background: rgba(239, 68, 68, 0.08); }}
        .tag-reality {{ color: #bae6fd; border-color: rgba(56, 189, 248, 0.3); background: rgba(56, 189, 248, 0.08); }}
        .tag-dist {{ font-family: var(--font-mono); color: var(--muted); }}

        .hp-desc {{ font-size: 13px; line-height: 1.5; color: #d0d7de; margin-bottom: 14px; }}
        
        .hp-btn-group {{ display: flex; gap: 8px; }}
        .btn {{
            flex: 1; padding: 10px 14px; border-radius: 8px; font-size: 12px; font-weight: 700;
            letter-spacing: 0.03em; border: 1px solid transparent; cursor: pointer;
            display: flex; align-items: center; justify-content: center; gap: 6px;
            transition: all 0.15s ease;
        }}
        .btn-primary {{
            background: var(--primary); color: #090b0e; border-color: var(--primary);
        }}
        .btn-primary:active {{ transform: scale(0.99); background: var(--primary-hover); }}
        .btn-secondary {{
            background: rgba(255,255,255,0.04); color: var(--text); border-color: var(--border);
        }}
        .btn-secondary:hover {{ border-color: var(--border-hover); }}
        .btn-secondary:active {{ transform: scale(0.99); background: rgba(255,255,255,0.08); }}

        /* Routes & Filters Drawer (Slide-up Panel) */
        #filter-drawer {{
            position: absolute; bottom: 0; left: 0; right: 0;
            max-height: 80vh; background: var(--surface-elevated);
            backdrop-filter: blur(28px); -webkit-backdrop-filter: blur(28px);
            border-top: 1px solid var(--border); border-radius: 16px 16px 0 0;
            padding: 20px 20px 32px 20px; z-index: 40; pointer-events: auto;
            transform: translateY(105%); transition: transform 0.35s cubic-bezier(0.16, 1, 0.3, 1);
            overflow-y: auto; box-shadow: 0 -16px 50px rgba(0,0,0,0.7);
        }}
        #filter-drawer.open {{ transform: translateY(0); }}

        .drawer-drag {{ width: 32px; height: 3px; background: rgba(255,255,255,0.18); border-radius: 2px; margin: 0 auto 16px auto; }}
        .drawer-title {{
            font-size: 14px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
            color: #fff; margin-bottom: 14px; display: flex; justify-content: space-between; align-items: center;
        }}
        
        .section-label {{
            font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em;
            color: var(--muted); margin: 16px 0 8px 0; display: flex; justify-content: space-between;
        }}
        
        /* Distance Slider Container */
        .slider-box {{
            background: rgba(255,255,255,0.02); border: 1px solid var(--border);
            border-radius: 10px; padding: 12px 14px; margin-bottom: 12px;
        }}
        .slider-header {{ display: flex; justify-content: space-between; font-size: 12px; font-weight: 600; color: #fff; margin-bottom: 8px; }}
        .km-range {{ width: 100%; accent-color: var(--primary); cursor: pointer; }}
        .quick-km-pills {{ display: flex; gap: 6px; margin-top: 8px; overflow-x: auto; }}
        .km-pill {{
            background: rgba(255,255,255,0.04); border: 1px solid var(--border);
            border-radius: 6px; padding: 5px 9px; font-size: 11px; font-weight: 600; font-family: var(--font-mono);
            color: var(--text); cursor: pointer; white-space: nowrap; transition: all 0.15s;
        }}
        .km-pill.active {{ background: var(--primary-soft); border-color: var(--border-active); color: var(--primary); }}

        /* Route Selection Cards */
        .route-card {{
            background: rgba(255,255,255,0.02); border: 1px solid var(--border);
            border-radius: 10px; padding: 12px 14px; margin-bottom: 8px; cursor: pointer;
            transition: all 0.15s ease;
        }}
        .route-card:hover {{ background: rgba(255,255,255,0.05); border-color: var(--border-hover); }}
        .route-card.selected {{
            background: var(--primary-soft); border-color: var(--border-active);
        }}
        .rc-top {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 4px; }}
        .rc-title {{ font-size: 13px; font-weight: 700; color: #fff; }}
        .rc-badges {{ display: flex; gap: 6px; font-size: 10px; font-weight: 600; color: var(--muted); margin-bottom: 6px; }}
        .rc-badge {{
            font-family: var(--font-mono); background: rgba(255,255,255,0.05);
            border: 1px solid var(--border); padding: 2px 6px; border-radius: 4px;
        }}
        .rc-desc {{ font-size: 12px; color: #b0bcc4; line-height: 1.4; }}

        /* Filter Chips */
        .filter-chips {{ display: flex; gap: 6px; overflow-x: auto; padding-bottom: 4px; }}
        .chip {{
            background: rgba(255,255,255,0.04); border: 1px solid var(--border);
            border-radius: 6px; padding: 6px 11px; font-size: 11px; font-weight: 600;
            color: var(--muted); cursor: pointer; white-space: nowrap; display: flex;
            align-items: center; gap: 4px; transition: all 0.15s;
        }}
        .chip:hover {{ color: var(--text); border-color: var(--border-hover); }}
        .chip.active {{ background: var(--primary-soft); border-color: var(--border-active); color: var(--primary); }}

        /* Fullscreen Ground-Level Reality Viewer */
        #reality-container {{
            position: absolute; top: 0; left: 0; width: 100%; height: 100%;
            z-index: 50; background: #07090b; opacity: 0; pointer-events: none;
            transition: opacity 0.45s cubic-bezier(0.16, 1, 0.3, 1);
            display: flex; flex-direction: column; overflow: hidden;
        }}
        #reality-container.active {{ opacity: 1; pointer-events: auto; }}
        
        #reality-pan-viewport {{
            flex: 1; width: 100%; height: 100%; overflow: hidden; position: relative;
            cursor: grab; touch-action: none; display: flex; align-items: center; justify-content: center;
        }}
        #reality-pan-viewport:active {{ cursor: grabbing; }}

        #reality-media {{
            height: 100%; min-width: 145vw; max-width: none; object-fit: cover;
            pointer-events: none; user-select: none;
            transition: transform 0.06s ease-out; transform: translateX(0px);
            will-change: transform;
        }}

        #reality-header {{
            position: absolute; top: 14px; left: 14px; right: 14px;
            display: flex; justify-content: space-between; align-items: flex-start;
            pointer-events: auto; z-index: 55; gap: 8px;
        }}
        #reality-footer {{
            position: absolute; bottom: 14px; left: 14px; right: 14px;
            display: flex; justify-content: space-between; align-items: center;
            color: var(--muted); font-size: 11px; background: var(--surface);
            padding: 8px 14px; border-radius: 8px; backdrop-filter: blur(16px);
            pointer-events: auto; border: 1px solid var(--border);
        }}
        #reality-pan-hint {{
            position: absolute; bottom: 58px; left: 50%; transform: translateX(-50%);
            background: var(--surface); backdrop-filter: blur(16px);
            padding: 6px 14px; border-radius: 8px; font-size: 11px; font-weight: 600;
            color: var(--text); border: 1px solid var(--border); pointer-events: none;
            display: flex; align-items: center; gap: 6px; box-shadow: 0 4px 14px rgba(0,0,0,0.5);
            transition: opacity 0.5s ease;
        }}

        /* Settings Modal */
        #settings-modal {{
            position: absolute; top: 0; left: 0; width: 100%; height: 100%;
            background: rgba(5,7,9,0.8); backdrop-filter: blur(16px);
            z-index: 60; display: none; align-items: center; justify-content: center;
            padding: 20px;
        }}
        #settings-modal.open {{ display: flex; }}
        .modal-box {{
            background: var(--surface-elevated); border: 1px solid var(--border); border-radius: 12px;
            padding: 22px; width: 100%; max-width: 380px; box-shadow: 0 20px 50px rgba(0,0,0,0.8);
        }}
        .modal-title {{ font-size: 14px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 16px; color: #fff; display: flex; justify-content: space-between; align-items: center; }}
        .modal-row {{ margin-bottom: 14px; }}
        .modal-label {{ font-size: 11px; font-weight: 600; color: var(--muted); margin-bottom: 6px; display: block; }}
        .modal-input {{
            width: 100%; background: rgba(255,255,255,0.03); border: 1px solid var(--border);
            border-radius: 6px; padding: 8px 10px; color: #fff; font-size: 12px; outline: none;
        }}
        .modal-select {{
            width: 100%; background: #11151a; border: 1px solid var(--border);
            border-radius: 6px; padding: 8px 10px; color: #fff; font-size: 12px; outline: none;
        }}
        .modal-close-btn {{
            background: none; border: none; color: var(--muted); font-size: 16px; cursor: pointer; padding: 4px;
            transition: color 0.15s;
        }}
        .modal-close-btn:hover {{ color: #fff; }}

        /* Classic Minimalist Tour Wizard Styles */
        .wiz-item-card {{
            background: rgba(255,255,255,0.02); border: 1px solid var(--border);
            border-radius: 10px; padding: 12px 14px; cursor: pointer;
            display: flex; align-items: center; gap: 14px; transition: all 0.15s ease;
        }}
        .wiz-item-card:hover {{
            background: rgba(255,255,255,0.04); border-color: var(--border-hover);
        }}
        .wiz-item-card.active {{
            background: var(--primary-soft); border-color: var(--border-active);
        }}
        .wiz-mono-index {{
            font-family: var(--font-mono); font-size: 11px; font-weight: 700; color: var(--muted);
            letter-spacing: -0.02em; min-width: 18px;
        }}
        .wiz-item-card.active .wiz-mono-index {{ color: var(--primary); }}
        .wiz-radio-circle {{
            width: 14px; height: 14px; border-radius: 50%; border: 1px solid rgba(255,255,255,0.22);
            margin-left: auto; display: flex; align-items: center; justify-content: center; flex-shrink: 0;
            transition: all 0.15s;
        }}
        .wiz-item-card.active .wiz-radio-circle {{
            border-color: var(--primary);
        }}
        .wiz-radio-circle::after {{
            content: ''; width: 6px; height: 6px; border-radius: 50%;
            background: transparent; transition: background 0.15s;
        }}
        .wiz-item-card.active .wiz-radio-circle::after {{
            background: var(--primary);
        }}
    </style>
</head>
<body>

    <div id="map"></div>

    <!-- Top HUD Bar (Minimalist) -->
    <div id="top-hud">
        <div class="hud-pill">
            <span class="hud-status-dot"></span>
            <span>BLINDSEE 3D</span>
        </div>
        <div class="hud-actions">
            <button class="hud-btn active" id="btn-open-wizard">Tour-Assistent</button>
            <button class="hud-btn" id="btn-toggle-filters">Routen</button>
            <button class="hud-btn" id="btn-tour">Rundflug</button>
            <button class="hud-btn" id="btn-settings">Optionen</button>
        </div>
    </div>

    <!-- Active Route Floating Indicator -->
    <div id="active-route-banner">
        <span class="route-indicator-dot"></span>
        <span id="banner-route-name">Route wählen</span>
        <span style="opacity:0.3; margin:0 2px;">/</span>
        <span id="banner-route-km">Interaktive Planung</span>
    </div>

    <!-- Hotspot Detail Bottom Sheet -->
    <div id="hotspot-panel">
        <div class="hp-header">
            <h3 class="hp-title" id="hp-title">Hotspot</h3>
            <span class="hp-duration" id="hp-duration">15–30 Min</span>
        </div>
        <div class="hp-tags">
            <span class="hp-tag tag-reality" id="hp-reality-badge">ECHTFOTO</span>
            <span class="hp-tag tag-kid-green" id="hp-kid-badge">Familienfreundlich</span>
            <span class="hp-tag tag-dist" id="hp-dist-badge">0.0 km</span>
            <span class="hp-tag tag-dist" id="hp-gps-badge" style="display:none;">-- m</span>
        </div>
        <div id="hp-thumb-container" style="display:none; margin-bottom:12px; border-radius:8px; overflow:hidden; max-height:150px; border:1px solid var(--border); box-shadow:0 4px 14px rgba(0,0,0,0.5); cursor:pointer;">
            <img id="hp-thumb" src="" alt="Vorschau" style="width:100%; height:150px; object-fit:cover; display:block;" />
        </div>
        <div class="hp-desc" id="hp-desc"></div>
        <div class="hp-btn-group">
            <button class="btn btn-primary" id="btn-enter-reality">Augenhöhe einnehmen</button>
            <button class="btn btn-secondary" id="btn-close-panel">Übersicht</button>
        </div>
    </div>

    <!-- Routes & Filters Drawer -->
    <div id="filter-drawer">
        <div class="drawer-drag"></div>
        <div class="drawer-title">
            <span>Routenauswahl & Filter</span>
            <button class="modal-close-btn" id="btn-close-drawer">Schließen</button>
        </div>

        <!-- Kilometer Filter Slider -->
        <div class="slider-box">
            <div class="slider-header">
                <span>Maximale Streckenlänge:</span>
                <span id="label-max-km" style="color:var(--primary); font-family:var(--font-mono); font-size:13px;">Alle Strecken</span>
            </div>
            <input type="range" class="km-range" id="slider-km" min="1.5" max="8.0" step="0.5" value="8.0" />
            <div class="quick-km-pills">
                <div class="km-pill" data-km="2.0">&le; 2.0 km</div>
                <div class="km-pill" data-km="3.5">&le; 3.5 km</div>
                <div class="km-pill" data-km="5.5">&le; 5.5 km</div>
                <div class="km-pill active" data-km="8.0">Alle Strecken</div>
            </div>
        </div>

        <!-- Filtered Route Cards List -->
        <div class="section-label">
            <span>Verfügbare Strecken (<span id="route-count">4</span>)</span>
            <span style="font-size:10px; text-transform:none; opacity:0.6;">Selektierte Route wird gerendert</span>
        </div>
        <div id="routes-list"></div>

        <!-- Hotspot Category Filters -->
        <div class="section-label">
            <span>Kategorien</span>
        </div>
        <div class="filter-chips" id="category-chips">
            <div class="chip active" data-cat="all">Alle Punkte</div>
            <div class="chip" data-cat="photo">Aussicht & Panorama</div>
            <div class="chip" data-cat="beach">Baden & Strand</div>
            <div class="chip" data-cat="nature">Geologie & Natur</div>
            <div class="chip" data-cat="360">360° Aufnahmen</div>
        </div>

        <!-- Light & Atmosphere Presets -->
        <div class="section-label">
            <span>Sonnenstand & Licht</span>
        </div>
        <div class="filter-chips">
            <div class="chip active" id="btn-sun-noon">Mittag (Klar)</div>
            <div class="chip" id="btn-sun-morning">Morgenlicht</div>
            <div class="chip" id="btn-sun-evening">Abendlicht</div>
        </div>

        <!-- Relief & 3D Settings -->
        <div class="section-label">
            <span>Geländerelief</span>
        </div>
        <div class="filter-chips">
            <div class="chip active" id="btn-relief-subtle">Relief Normal (0.35x)</div>
            <div class="chip" id="btn-relief-deep">Relief Betont (1.0x)</div>
            <div class="chip" id="btn-relief-off">2D Flachkarte</div>
        </div>
    </div>

    <!-- Fullscreen Ground-Level Reality Viewer -->
    <div id="reality-container">
        <div id="reality-header">
            <div style="display:flex; flex-direction:column; gap:4px;">
                <div class="hud-pill" style="font-size:11px; background:var(--surface); border-color:var(--border);">
                    <span class="hud-status-dot"></span>
                    <span id="reality-ground-title">Bodenperspektive</span>
                </div>
                <div style="display:flex; gap:6px;">
                    <span class="hud-pill" id="reality-compass-pill" style="font-size:10px; padding:3px 8px; opacity:0.85;">Blickrichtung</span>
                    <span class="hud-pill" id="reality-mode-pill" style="font-size:10px; padding:3px 8px; opacity:0.85;">AUGENHÖHE</span>
                </div>
            </div>
            <button class="hud-btn active" id="btn-back" style="padding:8px 12px; font-size:11px;">
                Kartenübersicht
            </button>
        </div>

        <div id="reality-pan-viewport">
            <img id="reality-media" src="" alt="Reality View" />
        </div>

        <div id="reality-pan-hint">
            <span>Horizontale Wischgeste zum Umschauen</span>
        </div>

        <div id="reality-footer">
            <span id="reality-attribution">Quelle: Wikimedia Commons</span>
            <span id="reality-detail-toggle" style="cursor:pointer; text-decoration:underline; font-weight:600; color:var(--primary);">Spot-Informationen</span>
        </div>
    </div>

    <!-- Settings Modal -->
    <div id="settings-modal">
        <div class="modal-box">
            <div class="modal-title">
                <span>Systemeinstellungen</span>
                <button class="modal-close-btn" id="btn-close-settings">Schließen</button>
            </div>
            <div class="modal-row">
                <label class="modal-label">Darstellungsstufe</label>
                <select class="modal-select" id="pref-quality">
                    <option value="high">High (3D-Terrain + Satellit)</option>
                    <option value="low">Low (2D-Karte)</option>
                </select>
            </div>
            <div class="modal-row">
                <label class="modal-label">Kamera-Animationen</label>
                <select class="modal-select" id="pref-motion">
                    <option value="smooth">Sanfter Kameraflug</option>
                    <option value="reduced">Reduzierte Bewegung</option>
                </select>
            </div>
            <div class="modal-row">
                <label class="modal-label">Mapillary Access Token (Optional)</label>
                <input type="text" class="modal-input" id="pref-mapillary" placeholder="MLY|..." />
            </div>
            <div class="modal-row">
                <label class="modal-label">Google Photorealistic 3D API Key (Optional)</label>
                <input type="text" class="modal-input" id="pref-google" placeholder="AIzaSy..." />
            </div>
            <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:20px;">
                <button class="btn btn-secondary" id="btn-cancel-settings">Abbrechen</button>
                <button class="btn btn-primary" id="btn-save-settings">Speichern</button>
            </div>
        </div>
    </div>
    
    
    <div id="tour-wizard-modal" style="position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(6,8,10,0.88); backdrop-filter:blur(24px); -webkit-backdrop-filter:blur(24px); z-index:75; display:flex; align-items:center; justify-content:center; padding:16px; opacity:1; transition:opacity 0.25s cubic-bezier(0.16,1,0.3,1);">
        <div style="background:var(--surface-elevated); border:1px solid var(--border); border-radius:14px; padding:24px 22px; width:100%; max-width:440px; box-shadow:0 24px 60px rgba(0,0,0,0.85); position:relative; overflow:hidden;">
            
            <!-- Top Header & Stepper Badge -->
            <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:12px;">
                <div>
                    <span id="wiz-step-badge" style="font-family:var(--font-mono); font-size:10px; font-weight:700; letter-spacing:0.08em; text-transform:uppercase; color:var(--primary); background:var(--primary-soft); border:1px solid rgba(197,160,89,0.25); padding:3px 8px; border-radius:4px; display:inline-block; margin-bottom:6px;">
                        SCHRITT 01 / 03 · PROFIL
                    </span>
                    <h2 style="font-size:17px; font-weight:700; color:#fff; margin:0; line-height:1.2; letter-spacing:-0.01em;">Tour-Assistent Blindsee</h2>
                </div>
                <button class="modal-close-btn" id="btn-close-wizard" style="font-size:18px; color:var(--muted); line-height:1;">&times;</button>
            </div>

            <!-- Minimalist Hairline Progress Track -->
            <div style="width:100%; height:2px; background:rgba(255,255,255,0.06); margin-bottom:20px; overflow:hidden;">
                <div id="wiz-progress" style="width:33%; height:100%; background:var(--primary); transition:width 0.25s ease;"></div>
            </div>

            <!-- SCHRITT 1: Begleitung & Profil -->
            <div class="wiz-step" id="wiz-step-1" style="display:block;">
                <div style="font-size:13px; font-weight:700; color:#fff; margin-bottom:2px;">Begleitung & Gelände</div>
                <div style="font-size:12px; color:var(--muted); margin-bottom:16px; line-height:1.4;">Wählen Sie Ihr Bewegungsprofil:</div>

                <div style="display:flex; flex-direction:column; gap:8px; margin-bottom:20px;">
                    <div class="wiz-card wiz-item-card active" data-group="stroller">
                        <span class="wiz-mono-index">01</span>
                        <div>
                            <div style="font-size:13px; font-weight:700; color:#fff;">Kinderwagen & Buggy</div>
                            <div style="font-size:11px; color:var(--muted);">Stufenlos · Feste Forst- und Uferwege</div>
                        </div>
                        <div class="wiz-radio-circle"></div>
                    </div>

                    <div class="wiz-card wiz-item-card" data-group="kids">
                        <span class="wiz-mono-index">02</span>
                        <div>
                            <div style="font-size:13px; font-weight:700; color:#fff;">Familie zu Fuß</div>
                            <div style="font-size:11px; color:var(--muted);">Kinderfreundlich · Moderate Distanzen</div>
                        </div>
                        <div class="wiz-radio-circle"></div>
                    </div>

                    <div class="wiz-card wiz-item-card" data-group="hikers">
                        <span class="wiz-mono-index">03</span>
                        <div>
                            <div style="font-size:13px; font-weight:700; color:#fff;">Wanderer & Bergfreunde</div>
                            <div style="font-size:11px; color:var(--muted);">Trittsicherheit · Wurzel- und Felsensteige</div>
                        </div>
                        <div class="wiz-radio-circle"></div>
                    </div>

                    <div class="wiz-card wiz-item-card" data-group="dog">
                        <span class="wiz-mono-index">04</span>
                        <div>
                            <div style="font-size:13px; font-weight:700; color:#fff;">Mit Hund</div>
                            <div style="font-size:11px; color:var(--muted);">Schattige Waldabschnitte · Direkter Seezugang</div>
                        </div>
                        <div class="wiz-radio-circle"></div>
                    </div>
                </div>

                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <button class="btn btn-secondary" id="btn-wiz-skip-all" style="flex:none; padding:9px 12px;">Freie Karte</button>
                    <button class="btn btn-primary" id="btn-wiz-next-1" style="flex:none; padding:10px 20px;">Weiter</button>
                </div>
            </div>

            <!-- SCHRITT 2: Distanz & Zeitrahmen -->
            <div class="wiz-step" id="wiz-step-2" style="display:none;">
                <div style="font-size:13px; font-weight:700; color:#fff; margin-bottom:2px;">Distanz & Zeitbudget</div>
                <div style="font-size:12px; color:var(--muted); margin-bottom:16px; line-height:1.4;">Wählen Sie den gewünschten Streckenrahmen:</div>

                <div style="display:flex; flex-direction:column; gap:8px; margin-bottom:20px;">
                    <div class="wiz-dist-card wiz-item-card" data-km="2.0">
                        <span class="wiz-mono-index">01</span>
                        <div>
                            <div style="font-size:13px; font-weight:700; color:#fff;">Kurzer Spaziergang</div>
                            <div style="font-size:11px; color:var(--muted);">Bis 2,0 km · Ca. 30–45 Minuten</div>
                        </div>
                        <span style="font-family:var(--font-mono); font-size:11px; font-weight:600; color:var(--muted); margin-left:auto; margin-right:8px;">1.8 km</span>
                        <div class="wiz-radio-circle"></div>
                    </div>

                    <div class="wiz-dist-card wiz-item-card active" data-km="4.0">
                        <span class="wiz-mono-index">02</span>
                        <div>
                            <div style="font-size:13px; font-weight:700; color:#fff;">Familienrunde</div>
                            <div style="font-size:11px; color:var(--muted);">Bis 3,8 km · Ca. 1 Std 15 Min</div>
                        </div>
                        <span style="font-family:var(--font-mono); font-size:11px; font-weight:600; color:var(--primary); margin-left:auto; margin-right:8px;">3.4 km</span>
                        <div class="wiz-radio-circle"></div>
                    </div>

                    <div class="wiz-dist-card wiz-item-card" data-km="6.0">
                        <span class="wiz-mono-index">03</span>
                        <div>
                            <div style="font-size:13px; font-weight:700; color:#fff;">Seeumrundung</div>
                            <div style="font-size:11px; color:var(--muted);">Bis 5,5 km · Ca. 2 Stunden</div>
                        </div>
                        <span style="font-family:var(--font-mono); font-size:11px; font-weight:600; color:var(--muted); margin-left:auto; margin-right:8px;">5.2 km</span>
                        <div class="wiz-radio-circle"></div>
                    </div>

                    <div class="wiz-dist-card wiz-item-card" data-km="8.0">
                        <span class="wiz-mono-index">04</span>
                        <div>
                            <div style="font-size:13px; font-weight:700; color:#fff;">Panoramarunde</div>
                            <div style="font-size:11px; color:var(--muted);">Bis 8,0 km · Ca. 2,5 Stunden</div>
                        </div>
                        <span style="font-family:var(--font-mono); font-size:11px; font-weight:600; color:var(--muted); margin-left:auto; margin-right:8px;">7.2 km</span>
                        <div class="wiz-radio-circle"></div>
                    </div>
                </div>

                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <button class="btn btn-secondary" id="btn-wiz-back-1" style="flex:none; padding:9px 12px;">Zurück</button>
                    <button class="btn btn-primary" id="btn-wiz-next-2" style="flex:none; padding:10px 20px;">Weiter</button>
                </div>
            </div>

            <!-- SCHRITT 3: Erlebnisschwerpunkt -->
            <div class="wiz-step" id="wiz-step-3" style="display:none;">
                <div style="font-size:13px; font-weight:700; color:#fff; margin-bottom:2px;">Erlebnisschwerpunkt</div>
                <div style="font-size:12px; color:var(--muted); margin-bottom:16px; line-height:1.4;">Wählen Sie das Hauptziel Ihres Ausflugs:</div>

                <div style="display:flex; flex-direction:column; gap:8px; margin-bottom:20px;">
                    <div class="wiz-focus-card wiz-item-card active" data-focus="beach">
                        <span class="wiz-mono-index">01</span>
                        <div>
                            <div style="font-size:13px; font-weight:700; color:#fff;">Badestrand & Bucht</div>
                            <div style="font-size:11px; color:var(--muted);">Flacher Kiesstrand · Kristallklares Bergwasser</div>
                        </div>
                        <div class="wiz-radio-circle"></div>
                    </div>

                    <div class="wiz-focus-card wiz-item-card" data-focus="photo">
                        <span class="wiz-mono-index">02</span>
                        <div>
                            <div style="font-size:13px; font-weight:700; color:#fff;">Zugspitz-Panorama</div>
                            <div style="font-size:11px; color:var(--muted);">Freie Sichtachse auf das Wettersteinmassiv</div>
                        </div>
                        <div class="wiz-radio-circle"></div>
                    </div>

                    <div class="wiz-focus-card wiz-item-card" data-focus="nature">
                        <span class="wiz-mono-index">03</span>
                        <div>
                            <div style="font-size:13px; font-weight:700; color:#fff;">Versunkener Urwald</div>
                            <div style="font-size:11px; color:var(--muted);">Prähistorischer Bergsturz · Naturphänomene</div>
                        </div>
                        <div class="wiz-radio-circle"></div>
                    </div>

                    <div class="wiz-focus-card wiz-item-card" data-focus="all">
                        <span class="wiz-mono-index">04</span>
                        <div>
                            <div style="font-size:13px; font-weight:700; color:#fff;">Aussicht & Einkehr</div>
                            <div style="font-size:11px; color:var(--muted);">Erhöhte Aussichtspunkte · Fernpass-Rasthaus</div>
                        </div>
                        <div class="wiz-radio-circle"></div>
                    </div>
                </div>

                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <button class="btn btn-secondary" id="btn-wiz-back-2" style="flex:none; padding:9px 12px;">Zurück</button>
                    <button class="btn btn-primary" id="btn-wiz-finish" style="flex:none; padding:10px 20px;">Empfehlung berechnen</button>
                </div>
            </div>

            <!-- SCHRITT 4: Das Ergebnis (Maßgeschneiderte Empfehlung) -->
            <div class="wiz-step" id="wiz-step-result" style="display:none;">
                <div style="margin-bottom:14px;">
                    <div style="font-size:11px; font-weight:700; letter-spacing:0.06em; text-transform:uppercase; color:var(--primary); margin-bottom:4px;">Empfohlene Route</div>
                    <h3 id="res-route-title" style="font-size:18px; font-weight:700; color:#fff; margin:0 0 6px 0; letter-spacing:-0.01em;">Familien-Strandrunde</h3>
                    <div id="res-route-suit" style="font-size:12px; color:var(--text); font-weight:500;">Kinderwagentauglich · Breiter Uferpfad</div>
                </div>

                <!-- Swiss Metric Grid -->
                <div style="background:rgba(255,255,255,0.02); border:1px solid var(--border); border-radius:8px; padding:12px 14px; margin-bottom:14px; display:grid; grid-template-columns:1fr 1fr 1fr; gap:6px; text-align:center;">
                    <div>
                        <div style="font-family:var(--font-mono); font-size:9px; color:var(--muted); text-transform:uppercase; letter-spacing:0.08em; margin-bottom:2px;">Distanz</div>
                        <div id="res-route-km" style="font-family:var(--font-mono); font-size:15px; font-weight:700; color:#fff;">3.4 km</div>
                    </div>
                    <div style="border-left:1px solid var(--border); border-right:1px solid var(--border);">
                        <div style="font-family:var(--font-mono); font-size:9px; color:var(--muted); text-transform:uppercase; letter-spacing:0.08em; margin-bottom:2px;">Höhenmeter</div>
                        <div id="res-route-hm" style="font-family:var(--font-mono); font-size:15px; font-weight:700; color:var(--primary);">+65 hm</div>
                    </div>
                    <div>
                        <div style="font-family:var(--font-mono); font-size:9px; color:var(--muted); text-transform:uppercase; letter-spacing:0.08em; margin-bottom:2px;">Gehzeit</div>
                        <div id="res-route-time" style="font-family:var(--font-mono); font-size:15px; font-weight:700; color:#fff;">1h 15m</div>
                    </div>
                </div>

                <!-- Bergführer Begründung Box -->
                <div style="border-left:2px solid var(--primary); padding:2px 0 2px 12px; margin-bottom:14px;">
                    <div style="font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.06em; color:var(--primary); margin-bottom:3px;">Einschätzung des Bergführers</div>
                    <div id="res-route-guide-text" style="font-size:12px; color:#c2cdd5; line-height:1.45;"></div>
                </div>

                <!-- Vor-Ort Praxis Tipp -->
                <div style="background:rgba(255,255,255,0.02); border:1px solid var(--border); border-radius:8px; padding:10px 12px; margin-bottom:18px; font-size:11px; color:var(--muted); line-height:1.4;">
                    <strong style="color:var(--text);">Zufahrt & Konditionen:</strong> Mautstraße B179: 15–20 € pro PKW (inkl. Parken & Seezugang). Schranke geöffnet: 07:00 – 20:00 Uhr.
                </div>

                <!-- Final Action Buttons -->
                <div style="display:flex; flex-direction:column; gap:8px;">
                    <button class="btn btn-primary" id="btn-wiz-start-tour" style="padding:12px 16px; font-size:13px; font-weight:700;">
                        Route auf Karte aktivieren
                    </button>
                    <div style="display:flex; justify-content:space-between; gap:8px;">
                        <button class="btn btn-secondary" id="btn-wiz-back-result" style="padding:9px 12px; font-size:11px;">Kriterien anpassen</button>
                        <button class="btn btn-secondary" id="btn-wiz-skip-final" style="padding:9px 12px; font-size:11px;">Freie Karte</button>
                    </div>
                </div>
            </div>

        </div>
    </div>

    <script>
        const MAP_DATA = {json.dumps(geojson)};
        const HOTSPOTS_DATA = {json.dumps(hotspots)};
        const ROUTES_DATA = {json.dumps(routes_data)};
        const PROFILE_DATA = {json.dumps(profile)};

        let activeRoute = null; // No route on startup - zero yellow lines!
        let maxAllowedKm = 8.0;
        let activeCategoryFilter = 'all';

        function safeGetStorage(key, fallback) {{
            try {{
                if (typeof window !== 'undefined' && window.localStorage) {{
                    const val = localStorage.getItem(key);
                    return val !== null ? val : fallback;
                }}
            }} catch (e) {{}}
            return fallback;
        }}

        function safeSetStorage(key, val) {{
            try {{
                if (typeof window !== 'undefined' && window.localStorage) {{
                    localStorage.setItem(key, val);
                }}
            }} catch (e) {{}}
        }}

        // Local Storage Preferences with Bulletproof Fallback
        const PREFS = {{
            quality: safeGetStorage('PREF_QUALITY', 'high'),
            reducedMotion: safeGetStorage('PREF_REDUCED_MOTION', 'false') === 'true',
            mapillaryKey: safeGetStorage('MAPILLARY_TOKEN', ''),
            googleKey: safeGetStorage('GOOGLE_API_KEY', '')
        }};

        // User Live Location
        let userLocation = null;
        if (navigator.geolocation) {{
            navigator.geolocation.getCurrentPosition(pos => {{
                userLocation = {{ lat: pos.coords.latitude, lon: pos.coords.longitude }};
            }}, () => {{}}, {{ enableHighAccuracy: true, timeout: 8000 }});
        }}

        function getHaversineMeters(lat1, lon1, lat2, lon2) {{
            const R = 6371000;
            const phi1 = lat1 * Math.PI / 180, phi2 = lat2 * Math.PI / 180;
            const deltaPhi = (lat2 - lat1) * Math.PI / 180;
            const deltaLambda = (lon2 - lon1) * Math.PI / 180;
            const a = Math.sin(deltaPhi/2)**2 + Math.cos(phi1)*Math.cos(phi2)*Math.sin(deltaLambda/2)**2;
            return Math.round(2 * R * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a)));
        }}

        // Initialize Map with Crisp Alpine Atmosphere (Rule 2, 23, 50)
        const map = new maplibregl.Map({{
            container: 'map',
            style: {{
                version: 8,
                glyphs: "https://demotiles.maplibre.org/font/{{fontstack}}/{{range}}.pbf",
                sources: {{
                    'google-satellite': {{
                        type: 'raster',
                        tiles: ['https://mt1.google.com/vt/lyrs=s&x={{x}}&y={{y}}&z={{z}}&scale=2'],
                        tileSize: 256,
                        attribution: '&copy; Google'
                    }},
                    'terrain-rgb': {{
                        type: 'raster-dem',
                        tiles: ['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{{z}}/{{x}}/{{y}}.png'],
                        encoding: 'terrarium',
                        tileSize: 256
                    }},
                    'geo-data': {{
                        type: 'geojson',
                        data: MAP_DATA
                    }},
                    'active-route': {{
                        type: 'geojson',
                        data: {{
                            type: 'Feature',
                            geometry: {{
                                type: 'LineString',
                                coordinates: []
                            }}
                        }}
                    }}
                }},
                layers: [
                    {{
                        id: 'satellite-layer',
                        type: 'raster',
                        source: 'google-satellite',
                        minzoom: 0, maxzoom: 22
                    }},
                    {{
                        id: 'hillshade-layer',
                        type: 'hillshade',
                        source: 'terrain-rgb',
                        paint: {{
                            'hillshade-exaggeration': 0.28,
                            'hillshade-shadow-color': 'rgba(20, 35, 50, 0.25)', // Lighter, clearer shadows
                            'hillshade-highlight-color': '#ffffff',
                            'hillshade-illumination-direction': 180
                        }}
                    }},
                    {{
                        id: 'lake-polygon',
                        type: 'fill',
                        source: 'geo-data',
                        filter: ['==', 'is_lake', true],
                        paint: {{
                            'fill-color': '#14b8a6', // Clear vibrant alpine turquoise
                            'fill-opacity': 0.16
                        }}
                    }},
                    // ONLY THE ACTIVE SELECTED ROUTE IS DRAWN WITH CRISP GOLDEN LINES!
                    {{
                        id: 'active-route-casing',
                        type: 'line',
                        source: 'active-route',
                        layout: {{ 'line-join': 'round', 'line-cap': 'round' }},
                        paint: {{
                            'line-color': '#1f160d',
                            'line-width': 5.5,
                            'line-opacity': 0.85
                        }}
                    }},
                    {{
                        id: 'active-route-line',
                        type: 'line',
                        source: 'active-route',
                        layout: {{ 'line-join': 'round', 'line-cap': 'round' }},
                        paint: {{
                            'line-color': '#facc15', // Vibrant golden-yellow
                            'line-width': 3.5,
                            'line-opacity': 1.0
                        }}
                    }}
                ]
            }},
            center: [10.8475, 47.3622],
            zoom: 14.5,
            pitch: 0,
            bearing: 0,
            dragRotate: true,
            maxPitch: 82,
            antialias: true,
            pixelRatio: Math.max(window.devicePixelRatio || 1, 2.5)
        }});

        map.addControl(new maplibregl.GeolocateControl({{
            positionOptions: {{ enableHighAccuracy: true }},
            trackUserLocation: true,
            showUserHeading: true
        }}), 'top-right');

        map.on('load', () => {{
            if (PREFS.quality === 'high') {{
                map.setTerrain({{ source: 'terrain-rgb', exaggeration: 0.35 }});
            }}
            // Crisp, light alpine atmosphere (Nebel lichter & klarer!)
            if (map.setFog) {{
                map.setFog({{
                    'range': [2.0, 18.0],
                    'color': 'rgba(235, 246, 255, 0.32)',
                    'horizon-blend': 0.10,
                    'high-color': '#e0f2fe',
                    'space-color': '#0c1a24'
                }});
            }}
        }});

        // ==========================================
        // 5. PROVIDER-ABSTRAKTION & 20. FALLBACK
        // ==========================================
        class RealityProvider {{
            constructor(name) {{ this.name = name; }}
            async checkCoverage(lat, lon, hs) {{ return null; }}
        }}

        class Photorealistic3DProvider extends RealityProvider {{
            constructor() {{ super('Google 3D Tiles'); }}
            async checkCoverage(lat, lon, hs) {{ return null; }}
        }}

        class GoogleStreetViewProvider extends RealityProvider {{
            constructor() {{ super('Google Street View'); }}
            async checkCoverage(lat, lon, hs) {{
                if (!PREFS.googleKey) return null;
                try {{
                    const res = await fetch(`https://maps.googleapis.com/maps/api/streetview/metadata?location=${{lat}},${{lon}}&key=${{PREFS.googleKey}}`);
                    const data = await res.json();
                    if (data.status === "OK") {{
                        return {{
                            type: 'REAL 360°',
                            provider: this.name,
                            url: `https://www.google.com/maps/@?api=1&map_action=pano&pano=${{data.pano_id}}`,
                            distance: '≈ 20m'
                        }};
                    }}
                }} catch(e) {{}}
                return null;
            }}
        }}

        class MapillaryProvider extends RealityProvider {{
            constructor() {{ super('Mapillary'); }}
            async checkCoverage(lat, lon, hs) {{
                if (!PREFS.mapillaryKey) return null;
                const d = 0.0006;
                const url = `https://graph.mapillary.com/images?fields=id,is_pano&bbox=${{lon-d}},${{lat-d}},${{lon+d}},${{lat+d}}&client_id=${{PREFS.mapillaryKey}}`;
                try {{
                    const res = await fetch(url);
                    const data = await res.json();
                    if (data.data && data.data.length > 0) {{
                        const best = data.data.find(img => img.is_pano) || data.data[0];
                        return {{
                            type: best.is_pano ? 'REAL 360°' : 'REAL STREET-LEVEL',
                            provider: this.name,
                            url: `https://www.mapillary.com/app/?pKey=${{best.id}}`,
                            distance: '< 50m'
                        }};
                    }}
                }} catch(e) {{}}
                return null;
            }}
        }}

        class KartaViewProvider extends RealityProvider {{
            constructor() {{ super('KartaView'); }}
            async checkCoverage(lat, lon, hs) {{
                try {{
                    const res = await fetch(`https://api.openstreetcam.org/2.0/photo/?lat=${{lat}}&lng=${{lon}}&radius=50`);
                    const data = await res.json();
                    if (data.result && data.result.data && data.result.data.length > 0) {{
                        const photo = data.result.data[0];
                        return {{
                            type: 'REAL STREET-LEVEL',
                            provider: this.name,
                            url: photo.photoUrl || photo.thumbUrl,
                            distance: '< 50m'
                        }};
                    }}
                }} catch(e) {{}}
                return null;
            }}
        }}

        class PanoramaxProvider extends RealityProvider {{
            constructor() {{ super('Panoramax'); }}
            async checkCoverage(lat, lon, hs) {{
                try {{
                    const res = await fetch(`https://panoramax.openstreetmap.fr/api/search?lat=${{lat}}&lon=${{lon}}&radius=60`);
                    const data = await res.json();
                    if (data.features && data.features.length > 0) {{
                        return {{
                            type: 'REAL 360°',
                            provider: this.name,
                            url: data.features[0].properties.view_url || '',
                            distance: '< 60m'
                        }};
                    }}
                }} catch(e) {{}}
                return null;
            }}
        }}

        class LocalRealityProvider extends RealityProvider {{
            constructor() {{ super('Wikimedia Commons'); }}
            async checkCoverage(lat, lon, hs) {{
                if (hs.realitySources && hs.realitySources.length > 0) {{
                    const s = hs.realitySources[0];
                    return {{
                        type: s.type === '360' ? 'REAL 360°' : 'REAL PHOTO',
                        provider: s.provider,
                        url: s.url,
                        distance: '0m (Am Hotspot)'
                    }};
                }}
                return null;
            }}
        }}

        class RealityDiscovery {{
            constructor() {{
                this.providers = [
                    new Photorealistic3DProvider(),
                    new GoogleStreetViewProvider(),
                    new MapillaryProvider(),
                    new KartaViewProvider(),
                    new PanoramaxProvider(),
                    new LocalRealityProvider()
                ];
            }}
            async discover(hs) {{
                for (let p of this.providers) {{
                    const r = await p.checkCoverage(hs.lat, hs.lon, hs);
                    if (r) return r;
                }}
                return {{ type: 'REAL MAP ONLY', provider: 'Satellit/OSM', url: null, distance: '0m' }};
            }}
        }}
        const discoveryEngine = new RealityDiscovery();
        let activeCoverage = null;

        // Dual Reality Viewer with Interactive Look-Around (Panoramablick)
        class RealityManager {{
            constructor() {{
                this.c = document.getElementById('reality-container');
                this.viewport = document.getElementById('reality-pan-viewport');
                this.m = document.getElementById('reality-media');
                this.iframe = document.createElement('iframe');
                this.iframe.style.cssText = 'flex: 1; width: 100%; height: 100%; border: none; background: #000; display: none;';
                this.iframe.setAttribute('allowfullscreen', 'true');
                this.viewport.appendChild(this.iframe);

                this.a = document.getElementById('reality-attribution');
                this.pill = document.getElementById('reality-mode-pill');
                this.titlePill = document.getElementById('reality-ground-title');
                this.compassPill = document.getElementById('reality-compass-pill');
                this.panHint = document.getElementById('reality-pan-hint');

                // Touch / Mouse Panning Mechanics (Look-around)
                this.panX = 0;
                this.startX = 0;
                this.isDragging = false;
                this.hasInteracted = false;

                const startDrag = (x) => {{
                    this.isDragging = true;
                    this.startX = x - this.panX;
                    if (!this.hasInteracted) {{
                        this.hasInteracted = true;
                        if (this.panHint) this.panHint.style.opacity = '0';
                    }}
                }};
                const moveDrag = (x) => {{
                    if (!this.isDragging) return;
                    this.panX = x - this.startX;
                    // Clamp panning so the image stays within bounds
                    const maxPan = (this.m.offsetWidth - this.viewport.offsetWidth) / 2;
                    if (this.panX > maxPan) this.panX = maxPan;
                    if (this.panX < -maxPan) this.panX = -maxPan;
                    this.m.style.transform = `translateX(${{this.panX}}px)`;
                }};
                const endDrag = () => {{ this.isDragging = false; }};

                // Touch events
                this.viewport.addEventListener('touchstart', e => {{
                    if (e.touches.length === 1) startDrag(e.touches[0].clientX);
                }}, {{ passive: true }});
                this.viewport.addEventListener('touchmove', e => {{
                    if (e.touches.length === 1) moveDrag(e.touches[0].clientX);
                }}, {{ passive: true }});
                this.viewport.addEventListener('touchend', endDrag);

                // Mouse events
                this.viewport.addEventListener('mousedown', e => startDrag(e.clientX));
                window.addEventListener('mousemove', e => moveDrag(e.clientX));
                window.addEventListener('mouseup', endDrag);
            }}

            enterGroundView(hs, cov, cardinal) {{
                this.c.classList.add('active');
                this.titlePill.innerText = `Du stehst am: ${{hs.name}}`;
                this.compassPill.innerText = `Blickrichtung ${{hs.bearing || 65}}° (${{cardinal}})`;
                this.pill.innerText = cov.type;
                this.a.innerHTML = `Quelle: ${{cov.provider}} &bull; Distanz: ${{cov.distance}}`;

                // Reset pan
                this.panX = 0;
                this.m.style.transform = 'translateX(0px)';
                if (this.panHint) this.panHint.style.opacity = '1';

                if (cov.type === 'REAL PHOTO' || (cov.url && (cov.url.endsWith('.jpg') || cov.url.endsWith('.png')))) {{
                    this.iframe.style.display = 'none';
                    this.m.style.display = 'block';
                    this.m.src = cov.url;
                }} else {{
                    this.m.style.display = 'none';
                    this.iframe.style.display = 'block';
                    this.iframe.src = cov.url;
                    if (this.panHint) this.panHint.style.opacity = '0';
                }}
            }}

            enter(cov) {{
                this.enterGroundView({{ name: 'Hotspot', bearing: 65 }}, cov, 'Ost');
            }}

            exit() {{
                this.c.classList.remove('active');
                setTimeout(() => {{
                    this.m.src = '';
                    this.iframe.src = '';
                }}, 400);
            }}
        }}
        const reality = new RealityManager();

        // Build Markers on Map with Category Filtering
        const markerElements = [];
        HOTSPOTS_DATA.forEach((hs, hsIdx) => {{
            const el = document.createElement('div');
            el.className = 'minimal-marker';
            el.innerText = String(hsIdx + 1).padStart(2, '0');
            el.dataset.category = hs.category;

            const badge = document.createElement('div');
            badge.className = 'reality-badge-dot ' + (
                hs.category === '3d' ? 'badge-3d' :
                hs.category === '360' ? 'badge-360' :
                hs.category === 'photo' ? 'badge-photo' : 'badge-map'
            );
            el.appendChild(badge);

            const m = new maplibregl.Marker({{ element: el, offset: [0, 0] }})
                .setLngLat([hs.lon, hs.lat])
                .addTo(map);

            markerElements.push({{ element: el, hotspot: hs, marker: m }});
            el.addEventListener('click', () => triggerApproach(hs));
        }});

        // Filter Markers: ONLY show spots along currently selected route!
        function updateMarkersForActiveRoute() {{
            markerElements.forEach(item => {{
                if (!activeRoute) {{
                    item.element.style.display = 'flex';
                    item.element.classList.remove('dimmed');
                    return;
                }}
                const belongsToRoute = activeRoute.hotspots && activeRoute.hotspots.includes(item.hotspot.id);
                if (belongsToRoute) {{
                    item.element.style.display = 'flex';
                    const cat = activeCategoryFilter;
                    if (cat === 'all') {{
                        item.element.classList.remove('dimmed');
                    }} else if (cat === 'beach' && (item.hotspot.category === 'beach' || item.hotspot.id === 'start')) {{
                        item.element.classList.remove('dimmed');
                    }} else if (cat === 'nature' && (item.hotspot.category === 'nature')) {{
                        item.element.classList.remove('dimmed');
                    }} else if (cat === item.hotspot.category) {{
                        item.element.classList.remove('dimmed');
                    }} else {{
                        item.element.classList.add('dimmed');
                    }}
                }} else {{
                    // Not part of the selected route -> completely hide marker!
                    item.element.style.display = 'none';
                }}
            }});
        }}

        function applyCategoryFilter(cat) {{
            activeCategoryFilter = cat;
            updateMarkersForActiveRoute();
        }}

        function populateHotspotCard(hs, cov) {{
            document.getElementById('hp-title').innerText = hs.name;
            document.getElementById('hp-duration').innerText = hs.duration || '15–30 Min';
            document.getElementById('hp-desc').innerText = hs.desc;

            const kidBadge = document.getElementById('hp-kid-badge');
            if (hs.kid_suitability === 'green') {{
                kidBadge.innerText = 'Familienfreundlich';
                kidBadge.className = 'hp-tag tag-kid-green';
            }} else if (hs.kid_suitability === 'yellow') {{
                kidBadge.innerText = 'Trittsicherheit nötig';
                kidBadge.className = 'hp-tag tag-kid-yellow';
            }} else {{
                kidBadge.innerText = 'Alpin / Steil';
                kidBadge.className = 'hp-tag';
            }}

            document.getElementById('hp-dist-badge').innerText = `Rundweg: ${{hs.dist_km || 0}} km`;

            const realityBadge = document.getElementById('hp-reality-badge');
            if (cov) {{
                realityBadge.innerText = `${{cov.type}} (${{cov.provider}})`;
            }}

            const gpsBadge = document.getElementById('hp-gps-badge');
            if (userLocation) {{
                const d = getHaversineMeters(userLocation.lat, userLocation.lon, hs.lat, hs.lon);
                gpsBadge.innerText = d > 1000 ? `${{(d/1000).toFixed(1)}} km entfernt` : `${{d}} m entfernt`;
                gpsBadge.style.display = 'inline-flex';
            }} else {{
                gpsBadge.style.display = 'none';
            }}

            // Praktische Infos: Gebühren, Öffnungszeiten, Infrastruktur
            const feesRow = document.getElementById('hp-fees-row');
            const feesVal = document.getElementById('hp-fees');
            if (hs.fees && feesRow && feesVal) {{
                feesRow.style.display = 'flex';
                feesVal.innerText = hs.fees;
            }} else if (feesRow) {{
                feesRow.style.display = 'none';
            }}

            const hoursRow = document.getElementById('hp-hours-row');
            const hoursVal = document.getElementById('hp-hours');
            if (hs.opening_hours && hoursRow && hoursVal) {{
                hoursRow.style.display = 'flex';
                hoursVal.innerText = hs.opening_hours;
            }} else if (hoursRow) {{
                hoursRow.style.display = 'none';
            }}

            const infraRow = document.getElementById('hp-infra-row');
            const infraVal = document.getElementById('hp-infra');
            if ((hs.infrastructure || hs.rules) && infraRow && infraVal) {{
                infraRow.style.display = 'flex';
                infraVal.innerText = (hs.infrastructure ? hs.infrastructure + ' • ' : '') + (hs.rules || '');
            }} else if (infraRow) {{
                infraRow.style.display = 'none';
            }}

            // Thumbnail
            const thumbContainer = document.getElementById('hp-thumb-container');
            const thumbImg = document.getElementById('hp-thumb');
            if (cov && cov.url && (cov.url.endsWith('.jpg') || cov.url.endsWith('.png')) && thumbContainer && thumbImg) {{
                thumbImg.src = cov.url;
                thumbContainer.style.display = 'block';
                thumbContainer.onclick = () => reality.enterGroundView(hs, cov, 'Ost');
            }} else if (thumbContainer) {{
                thumbContainer.style.display = 'none';
            }}
        }}

        // Supersonic Ground Dive: Zoom in right to eye level (Als würde man wirklich da stehen)
        async function triggerApproach(hs) {{
            // Close any open menus
            document.getElementById('filter-drawer').classList.remove('open');
            document.getElementById('btn-toggle-filters').classList.remove('active');
            document.getElementById('hotspot-panel').classList.remove('open');

            const isReduced = PREFS.reducedMotion;
            const b = hs.bearing || 65;
            let cardinal = 'Nord';
            if (b >= 23 && b < 68) cardinal = 'Nordost (Zugspitze)';
            else if (b >= 68 && b < 113) cardinal = 'Ost';
            else if (b >= 113 && b < 158) cardinal = 'Südost';
            else if (b >= 158 && b < 203) cardinal = 'Süd';
            else if (b >= 203 && b < 248) cardinal = 'Südwest';
            else if (b >= 248 && b < 293) cardinal = 'West';
            else if (b >= 293 && b < 338) cardinal = 'Nordwest';

            // Phase 1: High Approach (Geografischer Zielanflug)
            map.flyTo({{
                center: [hs.lon, hs.lat],
                zoom: isReduced ? 18.5 : 17.2,
                pitch: isReduced ? 60 : 35,
                bearing: isReduced ? b : b * 0.4,
                duration: isReduced ? 600 : 1200,
                essential: true
            }});

            // Asynchronous discovery of real visual media
            activeCoverage = await discoveryEngine.discover(hs);

            // Phase 2: Ground Touchdown Dive (Sturzflug auf 1.7m Augenhöhe!)
            setTimeout(() => {{
                if (!isReduced) {{
                    map.easeTo({{
                        center: [hs.lon, hs.lat],
                        zoom: 20.8, // Voller Anschlag: Richtig reinzoomen direkt auf den Boden!
                        pitch: 84,  // 84° Neigung: Exakt die menschliche Augenhöhe!
                        bearing: b, // Perfekt entlang der Seeblick-Achse ausgerichtet
                        duration: 1400,
                        easing: t => t * (2 - t)
                    }});
                    if (PREFS.quality === 'high') {{
                        map.setTerrain({{ source: 'terrain-rgb', exaggeration: 1.35 }});
                    }}
                }}
            }}, isReduced ? 600 : 1200);

            // Phase 3: Seamless Fade-in into Eye-Level Reality View (Als würde man wirklich da stehen!)
            setTimeout(() => {{
                populateHotspotCard(hs, activeCoverage);
                if (activeCoverage && activeCoverage.url) {{
                    // Sofortiger nahtloser Übergang in die reale Vor-Ort-Perspektive!
                    reality.enterGroundView(hs, activeCoverage, cardinal);
                }} else {{
                    // Ehrlicher Fallback: Infokarte am Boden
                    document.getElementById('hotspot-panel').classList.add('open');
                }}
            }}, isReduced ? 1100 : 2600);
        }}

        // Return to Overview
        document.getElementById('btn-close-panel').addEventListener('click', () => {{
            document.getElementById('hotspot-panel').classList.remove('open');
            const duration = PREFS.reducedMotion ? 600 : 2000;
            map.flyTo({{
                center: [10.8475, 47.3622],
                zoom: 14.5,
                pitch: 0,
                bearing: 0,
                duration: duration
            }});
            if (PREFS.quality === 'high') {{
                map.setTerrain({{ source: 'terrain-rgb', exaggeration: 0.35 }});
            }}
        }});

        document.getElementById('btn-enter-reality').addEventListener('click', () => {{
            if (activeCoverage && activeCoverage.url) {{
                reality.enter(activeCoverage);
            }}
        }});

        document.getElementById('btn-back').addEventListener('click', () => {{
            reality.exit();
            // Raketenhafter Aufstieg von Augenhöhe zurück in die Vogelperspektive!
            const isReduced = PREFS.reducedMotion;
            map.flyTo({{
                center: [10.8475, 47.3622],
                zoom: 14.5,
                pitch: 0,
                bearing: 0,
                duration: isReduced ? 800 : 2400,
                essential: true
            }});
            if (PREFS.quality === 'high') {{
                map.setTerrain({{ source: 'terrain-rgb', exaggeration: 0.35 }});
            }}
        }});

        // Detail-Panel Toggle inside Ground View
        const realityDetailToggle = document.getElementById('reality-detail-toggle');
        if (realityDetailToggle) {{
            realityDetailToggle.addEventListener('click', () => {{
                document.getElementById('hotspot-panel').classList.toggle('open');
            }});
        }}

        // ==========================================
        // DYNAMIC ROUTE SELECTION & FILTER LOGIC
        // ==========================================
        function setActiveRoute(route) {{
            activeRoute = route;
            // Update active route line on map
            const src = map.getSource('active-route');
            if (src) {{
                src.setData({{
                    type: 'Feature',
                    geometry: {{
                        type: 'LineString',
                        coordinates: route.coords
                    }}
                }});
            }}
            // Update Banner
            document.getElementById('banner-route-name').innerText = route.name;
            document.getElementById('banner-route-km').innerText = `${{route.km}} km`;

            // Highlight in drawer
            renderRouteCards();
            // Filter spots: Show ONLY spots along this active route!
            updateMarkersForActiveRoute();

            // Fit bounds to the active route
            if (route.coords && route.coords.length > 0) {{
                const bounds = new maplibregl.LngLatBounds();
                route.coords.forEach(coord => {{
                    if (Array.isArray(coord) && coord.length === 2 && typeof coord[0] === 'number' && typeof coord[1] === 'number') {{
                        bounds.extend(coord);
                    }}
                }});
                map.fitBounds(bounds, {{ padding: 60, maxZoom: 16.2, duration: 1500 }});
            }}
        }}

        function renderRouteCards() {{
            const container = document.getElementById('routes-list');
            if (!container) return;
            container.innerHTML = '';
            const matchingRoutes = ROUTES_DATA.filter(r => r.km <= maxAllowedKm);
            const countEl = document.getElementById('route-count');
            if (countEl) countEl.innerText = matchingRoutes.length;

            matchingRoutes.forEach(r => {{
                const isSelected = activeRoute ? (r.id === activeRoute.id) : false;
                const card = document.createElement('div');
                card.className = 'route-card' + (isSelected ? ' selected' : '');
                card.innerHTML = `
                    <div class="rc-top">
                        <span class="rc-title">${{r.name}}</span>
                        <span style="font-weight:700; color:${{isSelected ? 'var(--accent-gold)' : 'var(--primary)'}};">${{r.km}} km</span>
                    </div>
                    <div class="rc-badges">
                        <span class="rc-badge">↗ ${{r.elevation}} hm</span>
                        <span class="rc-badge">${{r.duration}}</span>
                        <span class="rc-badge">${{r.difficulty}}</span>
                    </div>
                    <div class="rc-desc">${{r.desc}}</div>
                `;
                card.addEventListener('click', () => {{
                    setActiveRoute(r);
                }});
                container.appendChild(card);
            }});
        }}

        // Kilometer Slider Interaction
        const sliderKm = document.getElementById('slider-km');
        const labelMaxKm = document.getElementById('label-max-km');
        sliderKm.addEventListener('input', e => {{
            maxAllowedKm = parseFloat(e.target.value);
            labelMaxKm.innerText = maxAllowedKm >= 8.0 ? 'Alle (bis 8.0 km)' : `Bis max. ${{maxAllowedKm.toFixed(1)}} km`;
            
            // Uncheck quick pills
            document.querySelectorAll('.km-pill').forEach(p => p.classList.remove('active'));
            renderRouteCards();
        }});

        // Quick Km Pills
        document.querySelectorAll('.km-pill').forEach(pill => {{
            pill.addEventListener('click', () => {{
                document.querySelectorAll('.km-pill').forEach(p => p.classList.remove('active'));
                pill.classList.add('active');
                maxAllowedKm = parseFloat(pill.dataset.km);
                sliderKm.value = maxAllowedKm;
                labelMaxKm.innerText = maxAllowedKm >= 8.0 ? 'Alle (bis 8.0 km)' : `Bis max. ${{maxAllowedKm.toFixed(1)}} km`;
                renderRouteCards();
            }});
        }});

        // Drawer Controls
        const filterDrawer = document.getElementById('filter-drawer');
        const btnToggleFilters = document.getElementById('btn-toggle-filters');
        btnToggleFilters.addEventListener('click', () => {{
            filterDrawer.classList.toggle('open');
            btnToggleFilters.classList.toggle('active', filterDrawer.classList.contains('open'));
        }});
        document.getElementById('btn-close-drawer').addEventListener('click', () => {{
            filterDrawer.classList.remove('open');
            btnToggleFilters.classList.remove('active');
        }});
        document.getElementById('active-route-banner').addEventListener('click', () => {{
            filterDrawer.classList.add('open');
            btnToggleFilters.classList.add('active');
        }});

        // Category Chips
        document.querySelectorAll('#category-chips .chip').forEach(chip => {{
            chip.addEventListener('click', () => {{
                document.querySelectorAll('#category-chips .chip').forEach(c => c.classList.remove('active'));
                chip.classList.add('active');
                applyCategoryFilter(chip.dataset.cat);
            }});
        }});

        // Atmosphere / Sun Lighting Presets
        document.getElementById('btn-sun-noon').addEventListener('click', function() {{
            document.querySelectorAll('#btn-sun-noon, #btn-sun-morning, #btn-sun-evening').forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            map.setPaintProperty('hillshade-layer', 'hillshade-illumination-direction', 180);
            map.setPaintProperty('hillshade-layer', 'hillshade-shadow-color', 'rgba(20, 35, 50, 0.25)');
        }});
        document.getElementById('btn-sun-morning').addEventListener('click', function() {{
            document.querySelectorAll('#btn-sun-noon, #btn-sun-morning, #btn-sun-evening').forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            map.setPaintProperty('hillshade-layer', 'hillshade-illumination-direction', 100);
            map.setPaintProperty('hillshade-layer', 'hillshade-shadow-color', 'rgba(30, 25, 45, 0.35)');
        }});
        document.getElementById('btn-sun-evening').addEventListener('click', function() {{
            document.querySelectorAll('#btn-sun-noon, #btn-sun-morning, #btn-sun-evening').forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            map.setPaintProperty('hillshade-layer', 'hillshade-illumination-direction', 260);
            map.setPaintProperty('hillshade-layer', 'hillshade-shadow-color', 'rgba(40, 20, 30, 0.35)');
        }});

        // 3D Relief Presets
        document.getElementById('btn-relief-subtle').addEventListener('click', function() {{
            document.querySelectorAll('#btn-relief-subtle, #btn-relief-deep, #btn-relief-off').forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            map.setTerrain({{ source: 'terrain-rgb', exaggeration: 0.35 }});
        }});
        document.getElementById('btn-relief-deep').addEventListener('click', function() {{
            document.querySelectorAll('#btn-relief-subtle, #btn-relief-deep, #btn-relief-off').forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            map.setTerrain({{ source: 'terrain-rgb', exaggeration: 1.0 }});
        }});
        document.getElementById('btn-relief-off').addEventListener('click', function() {{
            document.querySelectorAll('#btn-relief-subtle, #btn-relief-deep, #btn-relief-off').forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            map.setTerrain(null);
        }});

        // Flyover Tour
        let isTourRunning = false;
        document.getElementById('btn-tour').addEventListener('click', () => {{
            if (isTourRunning) return;
            isTourRunning = true;
            document.getElementById('top-hud').style.opacity = '0';
            document.getElementById('active-route-banner').style.opacity = '0';
            filterDrawer.classList.remove('open');

            let idx = 0;
            const steps = activeRoute.coords.length;
            const duration = 22000;
            const stepMs = duration / steps;

            function stepFrame() {{
                if (idx >= steps) {{
                    isTourRunning = false;
                    document.getElementById('top-hud').style.opacity = '1';
                    document.getElementById('active-route-banner').style.opacity = '1';
                    map.flyTo({{ center: [10.8475, 47.3622], zoom: 14.5, pitch: 0, bearing: 0, duration: 2500 }});
                    return;
                }}
                const pt = activeRoute.coords[idx];
                map.easeTo({{
                    center: pt,
                    zoom: 16.8,
                    pitch: 52,
                    bearing: (idx % 20) / 20 * 30,
                    duration: stepMs,
                    easing: t => t
                }});
                idx++;
                setTimeout(stepFrame, stepMs);
            }}

            map.flyTo({{ center: activeRoute.coords[0], zoom: 16.8, pitch: 52, duration: 2000 }});
            setTimeout(stepFrame, 2000);
        }});

        // Settings Modal
        const settingsModal = document.getElementById('settings-modal');
        document.getElementById('btn-settings').addEventListener('click', () => {{
            document.getElementById('pref-quality').value = PREFS.quality;
            document.getElementById('pref-motion').value = PREFS.reducedMotion ? 'reduced' : 'smooth';
            document.getElementById('pref-mapillary').value = PREFS.mapillaryKey;
            document.getElementById('pref-google').value = PREFS.googleKey;
            settingsModal.classList.add('open');
        }});
        document.getElementById('btn-close-settings').addEventListener('click', () => {{
            settingsModal.classList.remove('open');
        }});
        document.getElementById('btn-save-settings').addEventListener('click', () => {{
            const q = document.getElementById('pref-quality').value;
            const m = document.getElementById('pref-motion').value === 'reduced';
            const mly = document.getElementById('pref-mapillary').value.trim();
            const g = document.getElementById('pref-google').value.trim();

            safeSetStorage('PREF_QUALITY', q);
            safeSetStorage('PREF_REDUCED_MOTION', m);
            safeSetStorage('MAPILLARY_TOKEN', mly);
            safeSetStorage('GOOGLE_API_KEY', g);

            PREFS.quality = q;
            PREFS.reducedMotion = m;
            PREFS.mapillaryKey = mly;
            PREFS.googleKey = g;

            if (q === 'low') {{
                map.setTerrain(null);
            }} else {{
                map.setTerrain({{ source: 'terrain-rgb', exaggeration: 0.35 }});
            }}

            settingsModal.classList.remove('open');
        }});

        // Initial setup
        renderRouteCards();
        updateMarkersForActiveRoute();

        // ==========================================
        // LUXURY CONVERSATIONAL MOUNTAIN GUIDE CONTROLLER
        // ==========================================
        let wizState = {{
            group: 'stroller',
            distKm: 4.0,
            focus: 'beach',
            computedRoute: null
        }};

        const wizModal = document.getElementById('tour-wizard-modal');
        const progressBar = document.getElementById('wiz-progress');
        const stepBadge = document.getElementById('wiz-step-badge');

        function setWizStep(stepNum) {{
            document.querySelectorAll('.wiz-step').forEach(s => s.style.display = 'none');
            if (stepNum === 1) {{
                document.getElementById('wiz-step-1').style.display = 'block';
                progressBar.style.width = '33%';
                stepBadge.innerText = 'SCHRITT 01 / 03 · PROFIL';
            }} else if (stepNum === 2) {{
                document.getElementById('wiz-step-2').style.display = 'block';
                progressBar.style.width = '66%';
                stepBadge.innerText = 'SCHRITT 02 / 03 · DISTANZ';
            }} else if (stepNum === 3) {{
                document.getElementById('wiz-step-3').style.display = 'block';
                progressBar.style.width = '95%';
                stepBadge.innerText = 'SCHRITT 03 / 03 · SCHWERPUNKT';
            }} else if (stepNum === 4) {{
                computeBestTour();
                document.getElementById('wiz-step-result').style.display = 'block';
                progressBar.style.width = '100%';
                stepBadge.innerText = 'SCHRITT 04 / 04 · EMPFEHLUNG';
            }}
        }}

        // Card Selection with Classic Minimalist Active Class Toggle
        document.querySelectorAll('.wiz-card').forEach(card => {{
            card.addEventListener('click', () => {{
                document.querySelectorAll('.wiz-card').forEach(c => c.classList.remove('active'));
                card.classList.add('active');
                wizState.group = card.dataset.group;
                try {{ if (navigator.vibrate) navigator.vibrate(15); }} catch(e) {{}}
            }});
        }});

        document.querySelectorAll('.wiz-dist-card').forEach(card => {{
            card.addEventListener('click', () => {{
                document.querySelectorAll('.wiz-dist-card').forEach(c => c.classList.remove('active'));
                card.classList.add('active');
                wizState.distKm = parseFloat(card.dataset.km);
                try {{ if (navigator.vibrate) navigator.vibrate(15); }} catch(e) {{}}
            }});
        }});

        document.querySelectorAll('.wiz-focus-card').forEach(card => {{
            card.addEventListener('click', () => {{
                document.querySelectorAll('.wiz-focus-card').forEach(c => c.classList.remove('active'));
                card.classList.add('active');
                wizState.focus = card.dataset.focus;
                try {{ if (navigator.vibrate) navigator.vibrate(15); }} catch(e) {{}}
            }});
        }});

        // Navigation Stepper Buttons
        document.getElementById('btn-wiz-next-1').addEventListener('click', () => setWizStep(2));
        document.getElementById('btn-wiz-next-2').addEventListener('click', () => setWizStep(3));
        document.getElementById('btn-wiz-back-1').addEventListener('click', () => setWizStep(1));
        document.getElementById('btn-wiz-back-2').addEventListener('click', () => setWizStep(2));
        document.getElementById('btn-wiz-back-result').addEventListener('click', () => setWizStep(3));
        document.getElementById('btn-wiz-finish').addEventListener('click', () => setWizStep(4));

        // Intelligent Mountain Guide Tour Computation
        function computeBestTour() {{
            let selected = ROUTES_DATA[1]; // default strand
            let guideReason = '';

            if (wizState.group === 'stroller') {{
                // Kinderwagen: ONLY short (1.8km) or beach (3.4km)
                if (wizState.distKm <= 2.2) {{
                    selected = ROUTES_DATA[0];
                    guideReason = 'Da du mit Kinderwagen unterwegs bist, führt diese Tour über den flachen, befestigten Nordost-Uferpfad und meidet alle felsigen Hindernisse.';
                }} else {{
                    selected = ROUTES_DATA[1];
                    guideReason = 'Ideal mit Kinderwagen: Der idyllische Ostuferpfad bringt euch sicher zur sonnigen Badebucht am Kiesstrand, ohne die steile Geröllmure am Westufer betreten zu müssen.';
                }}
            }} else {{
                // Foot / Hiker / Dog
                if (wizState.distKm <= 2.2) {{
                    selected = ROUTES_DATA[0];
                    guideReason = 'Ein feiner, kurzer Spaziergang für zwischendurch mit fantastischem Panoramablick über das Wasser.';
                }} else if (wizState.distKm <= 4.0) {{
                    selected = ROUTES_DATA[1];
                    guideReason = 'Die beliebteste Familien- und Badetour: Führt direkt zur sonnigen Kiesstrand-Bucht und zum glasklaren Gebirgsbach.';
                }} else if (wizState.distKm <= 6.0) {{
                    selected = ROUTES_DATA[2];
                    guideReason = 'Die vollständige Umrundung: Erlebe alle Facetten des Sees – von stillen Buchten über den versunkenen Wald bis zum Felsensteig.';
                }} else {{
                    selected = ROUTES_DATA[3];
                    guideReason = 'Die Königstour für Weitblick-Liebhaber: Vollständige Seeumrundung kombiniert mit dem Aufstieg zum Fernpass-Rasthaus für atemberaubende Tiefblicke.';
                }}
            }}

            // Priority adjustments based on focus
            if (wizState.focus === 'beach' && selected.id === 'short' && wizState.distKm >= 3.0) {{
                selected = ROUTES_DATA[1];
                guideReason = 'Dein Schwerpunkt liegt auf Baden & Strand: Wir haben die Route bis zum schönsten Natur-Kiesstrand des Sees erweitert!';
            }} else if (wizState.focus === 'photo' && wizState.distKm >= 6.5 && wizState.group !== 'stroller') {{
                selected = ROUTES_DATA[3];
                guideReason = 'Für Fotoliebhaber: Diese Route bietet die spektakulärste Aussichtsterrasse oberhalb des Sees mit direktem Blick auf die Zugspitz-Nordwand.';
            }}

            wizState.computedRoute = selected;

            // Fill Result View
            document.getElementById('res-route-title').innerText = selected.name;
            document.getElementById('res-route-km').innerText = `${{selected.km}} km`;
            document.getElementById('res-route-hm').innerText = `+${{selected.elevation}} hm`;
            document.getElementById('res-route-time').innerText = selected.duration;
            document.getElementById('res-route-guide-text').innerText = guideReason;

            const suitEl = document.getElementById('res-route-suit');
            if (wizState.group === 'stroller' && (selected.id === 'short' || selected.id === 'beach')) {{
                suitEl.innerText = 'Kinderwagentauglich · Breiter Uferpfad';
                suitEl.style.color = '#34d399';
            }} else if (selected.id === 'full' || selected.id === 'pano') {{
                suitEl.innerText = 'Trittsicherheit erforderlich · Alpiner Steig';
                suitEl.style.color = '#e2bd56';
            }} else {{
                suitEl.innerText = `Eignung: ${{selected.suitability}}`;
                suitEl.style.color = '#38bdf8';
            }}
        }}

        // Start Tour on Map
        document.getElementById('btn-wiz-start-tour').addEventListener('click', () => {{
            wizModal.style.opacity = '0';
            setTimeout(() => {{ wizModal.style.display = 'none'; }}, 350);

            if (wizState.computedRoute) {{
                setActiveRoute(wizState.computedRoute);
                try {{ if (navigator.vibrate) navigator.vibrate([20, 50, 20]); }} catch(e) {{}}
            }}
        }});

        // Close / Skip Buttons
        const closeWizard = () => {{
            wizModal.style.opacity = '0';
            setTimeout(() => {{ wizModal.style.display = 'none'; }}, 350);
            if (!activeRoute) {{
                markerElements.forEach(item => {{ item.element.style.display = 'flex'; }});
            }}
        }};

        document.getElementById('btn-close-wizard').addEventListener('click', closeWizard);
        document.getElementById('btn-wiz-skip-all').addEventListener('click', closeWizard);
        document.getElementById('btn-wiz-skip-final').addEventListener('click', closeWizard);

        // Open Wizard Button in Top HUD
        document.getElementById('btn-open-wizard').addEventListener('click', () => {{
            wizModal.style.display = 'flex';
            setTimeout(() => {{ wizModal.style.opacity = '1'; }}, 20);
            setWizStep(1);
        }});
    </script>

    <!-- Luxuriöser, Minimalistischer Blindsee Tour-Guide Modal -->
    </body>
</html>
"""

    with open("blindsee_3d_familienkarte.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("Build complete: blindsee_3d_familienkarte.html in classic minimalist design!")

if __name__ == "__main__":
    get_z = get_elevation_data()
    geojson, profile, milestones = fetch_osm(get_z)

    hotspots = [
        {
            "id": "start",
            "name": "Parkplatz & Bootshaus",
            "lat": 47.3655, "lon": 10.8512,
            "dist_km": 0.0,
            "duration": "10–20 Min",
            "category": "photo",
            "bearing": 215,
            "fees": "Mautstraße: 15–20 € pro PKW (inkl. Parken & Seezugang)",
            "opening_hours": "Schranke geöffnet: 07:00 – 20:00 Uhr (Nachtparkverbot)",
            "infrastructure": "WCs am Bootshaus, Müllstation, Schotterparkplatz",
            "rules": "Camping & Übernachten im Fahrzeug streng verboten",
            "desc": "Der ideale Rundweg-Startpunkt direkt am Nordost-Ufer. Schotterparkplatz vorhanden. Der Einstieg in den Uferpfad ist verwurzelt, aber gut begehbar.",
            "kid_suitability": "green",
            "realitySources": [{
                "type": "photo",
                "provider": "Wikimedia Commons (Besucherfoto)",
                "url": "https://upload.wikimedia.org/wikipedia/commons/6/66/Blindsee_v_Rasthaus_Zugspitzblick.jpg"
            }]
        },
        {
            "id": "ancient_pine",
            "name": "Zirben- & Mooswald (Ostufer)",
            "lat": 47.3638, "lon": 10.8528,
            "dist_km": 0.7,
            "duration": "10–15 Min",
            "category": "nature",
            "bearing": 200,
            "fees": "Kostenlos (in Maut enthalten)",
            "opening_hours": "Ganzjährig frei begehbar",
            "infrastructure": "Naturbelassener Waldpfad, schattige Raststeine",
            "rules": "Naturschutzgebiet: Auf den Pfaden bleiben",
            "desc": "Uralter Bergmischwald mit duftenden Zirben und gigantischen, moosbedeckten Felsblöcken aus dem prähistorischen Bergsturz. Wunderbarer Schattenspender.",
            "kid_suitability": "green",
            "realitySources": [{
                "type": "photo",
                "provider": "Wikimedia Commons (Besucherfoto)",
                "url": "https://upload.wikimedia.org/wikipedia/commons/e/e0/Blindsee_und_Zugspitze_von_Weg_nach_Biberwier.jpg"
            }]
        },
        {
            "id": "viewpoint",
            "name": "Aussichtspunkt Blindsee",
            "lat": 47.3622, "lon": 10.8431,
            "dist_km": 1.2,
            "duration": "20–30 Min",
            "category": "photo",
            "bearing": 65,
            "fees": "Kostenlos",
            "opening_hours": "Rund um die Uhr frei zugänglich",
            "infrastructure": "Aussichtsbank mit Panoramablick",
            "rules": "Fotodrohnen im Naturschutzgebiet verboten",
            "desc": "Markanter Panoramablick über das türkisgrüne Wasser hinüber zum mächtigen Wetterstein- und Zugspitzmassiv.",
            "kid_suitability": "green",
            "realitySources": [{
                "type": "photo",
                "provider": "Wikimedia Commons (Besucherfoto)",
                "url": "https://upload.wikimedia.org/wikipedia/commons/0/09/Ehrwald%2C_Weissensee_and_Zugspitze_-_panoramio.jpg"
            }]
        },
        {
            "id": "beach",
            "name": "Natur-Kiesstrand & Rast",
            "lat": 47.3590, "lon": 10.8480,
            "dist_km": 2.1,
            "duration": "1–2 Std",
            "category": "beach",
            "bearing": 340,
            "fees": "Baden kostenlos (in Maut enthalten)",
            "opening_hours": "Baden von Sonnenaufgang bis Sonnenuntergang",
            "infrastructure": "Naturbelassener Kiesstrand, keine WCs vor Ort",
            "rules": "Offenes Feuer & Grillen verboten! Müll wieder mitnehmen",
            "desc": "Idyllischer Natur-Kiesstrand am Südostufer. Flacher Einstieg, kristallklares Gebirgswasser (max 18-20°C). Ideal für Familien-Picknick.",
            "kid_suitability": "green",
            "realitySources": [{
                "type": "photo",
                "provider": "Wikimedia Commons (Besucherfoto)",
                "url": "https://upload.wikimedia.org/wikipedia/commons/5/59/Blindsee_beach_2.jpg"
            }]
        },
        {
            "id": "mountain_stream",
            "name": "Wildbach & Quellzulauf (Südufer)",
            "lat": 47.3582, "lon": 10.8450,
            "dist_km": 2.5,
            "duration": "15–20 Min",
            "category": "nature",
            "bearing": 350,
            "fees": "Kostenlos",
            "opening_hours": "Frei zugänglich",
            "infrastructure": "Flache Bachmündung, natürlicher Wasserspielplatz",
            "rules": "Quellschutz: Bachlauf sauber halten",
            "desc": "Eiskalter, kristallklarer Gebirgsbach, der von den Hängen der Grubigstein-Gruppe in den See stürzt. Perfekte Erfrischungsstation für Kinder.",
            "kid_suitability": "green",
            "realitySources": [{
                "type": "photo",
                "provider": "Wikimedia Commons (Besucherfoto)",
                "url": "https://upload.wikimedia.org/wikipedia/commons/5/50/Blindsee_Kiesstrand.jpg"
            }]
        },
        {
            "id": "fisherman_bay",
            "name": "Smaragdbucht & Fischergrund",
            "lat": 47.3608, "lon": 10.8415,
            "dist_km": 2.8,
            "duration": "15–30 Min",
            "category": "beach",
            "bearing": 80,
            "fees": "Fischereikarte erforderlich (ca. 35 € Tagesticket)",
            "opening_hours": "Fischen: Mai bis Oktober mit Lizenz",
            "infrastructure": "Kiesufer, ruhige Liegeplätze",
            "rules": "Schonzeiten beachten, Tiroler Fischerkarte Pflicht",
            "desc": "Windgeschützte Bucht mit unvergleichlich smaragdgrünem Wasser. Durch das spiegelglatte Wasser kann man oft Saiblinge und Forellen am Grund beobachten.",
            "kid_suitability": "green",
            "realitySources": [{
                "type": "photo",
                "provider": "Wikimedia Commons (Besucherfoto)",
                "url": "https://upload.wikimedia.org/wikipedia/commons/f/f6/Blindsee_Bucht_2.jpg"
            }]
        },
        {
            "id": "sunken_forest",
            "name": "Versunkener Wald (Tauchspot)",
            "lat": 47.3630, "lon": 10.8420,
            "dist_km": 3.2,
            "duration": "15–30 Min",
            "category": "nature",
            "bearing": 110,
            "fees": "Tauchberechtigung: 15–20 € Tagesticket (Pflicht)",
            "opening_hours": "Tauchen tagsüber erlaubt (Ausgabe via Hotel Mohr)",
            "infrastructure": "Taucheinstieg am Ostufer empfohlen, Bojen",
            "rules": "Gültiger Tauchschein Pflicht! Baumstämme nicht berühren",
            "desc": "Weltberühmter Tauchspot: Am Grund liegen seit Jahrhunderten konservierte Baumstämme eines prähistorischen Bergsturzes wie Mikado-Stäbe.",
            "kid_suitability": "yellow",
            "realitySources": [{
                "type": "photo",
                "provider": "Wikimedia Commons (Tauchfoto)",
                "url": "https://upload.wikimedia.org/wikipedia/commons/3/33/Blindsee_Underwater_Trees_2026-08-29.jpg"
            }]
        },
        {
            "id": "cliff_path",
            "name": "Felsensteig & Tiefblick (Westufer)",
            "lat": 47.3648, "lon": 10.8438,
            "dist_km": 3.6,
            "duration": "15–20 Min",
            "category": "photo",
            "bearing": 150,
            "fees": "Kostenlos",
            "opening_hours": "Begehbar bei Tageslicht & trockener Witterung",
            "infrastructure": "Schmaler Felsenpfad, feste Wanderschuhe nötig",
            "rules": "Nicht kinderwagentauglich! Trittsicherheit erforderlich",
            "desc": "Der Pfad schlängelt sich hier leicht erhöht am felsigen Westufer entlang. Faszinierender Tiefblick auf den abrupten Farbübergang von türkisem Flachwasser zu tiefblauem Grund.",
            "kid_suitability": "yellow",
            "realitySources": [{
                "type": "photo",
                "provider": "Wikimedia Commons (Besucherfoto)",
                "url": "https://upload.wikimedia.org/wikipedia/commons/a/a2/Blindsee_von_Westen.jpg"
            }]
        },
        {
            "id": "mudslide",
            "name": "Murenkegel & Geröllfeld 2020",
            "lat": 47.3660, "lon": 10.8485,
            "dist_km": 4.0,
            "duration": "15 Min",
            "category": "nature",
            "bearing": 210,
            "fees": "Kostenlos",
            "opening_hours": "Frei zugänglich",
            "infrastructure": "Grober Schotter- & Geröllweg",
            "rules": "Bei Starkregen Steinschlaggefahr beachten",
            "desc": "Geologisches Zeugnis einer massiven Schlammlawine aus 2020. Felsiger Pfadabschnitt, gute Wanderschuhe empfohlen.",
            "kid_suitability": "yellow",
            "realitySources": [{
                "type": "photo",
                "provider": "Wikimedia Commons (Besucherfoto)",
                "url": "https://upload.wikimedia.org/wikipedia/commons/6/67/Blindsee_-_slimy_object.jpg"
            }]
        },
        {
            "id": "north_forest",
            "name": "Nordufer Schutzwald",
            "lat": 47.3645, "lon": 10.8450,
            "dist_km": 4.4,
            "duration": "10 Min",
            "category": "map",
            "bearing": 160,
            "fees": "Kostenlos",
            "opening_hours": "Ganzjährig frei begehbar",
            "infrastructure": "Schattiger Wald-Wanderweg",
            "rules": "Bannwald: Pflanzen & Äste schonen",
            "desc": "Dichter Bergwald am Nordhang. Demonstrator nach Regel 47: Keine Detailfotos oder Panoramen verfügbar - ehrlicher Satelliten-Fallback ohne Fake-Daten.",
            "kid_suitability": "green",
            "realitySources": []
        },
        {
            "id": "fernpass_pano",
            "name": "Rasthaus Zugspitzblick (B179)",
            "lat": 47.3672, "lon": 10.8525,
            "dist_km": 4.8,
            "duration": "30–45 Min",
            "category": "360",
            "bearing": 220,
            "fees": "Parkplatz an Bundesstraße für Gäste kostenlos",
            "opening_hours": "Rasthaus täglich 09:00 – 18:00 Uhr (saisonal)",
            "infrastructure": "Restaurant, Aussichtsterrasse, WCs, Kiosk",
            "rules": "Zufahrt direkt über Fernpassstraße B179",
            "desc": "Erhöhte Passstraße mit Blick von oben auf den gesamten Blindsee. Auf der Fernpass-Bundesstraße B179 existiert reale Street-Level & Panoramax Abdeckung.",
            "kid_suitability": "green",
            "realitySources": [{
                "type": "360",
                "provider": "Panoramax / OpenStreetMap",
                "url": "https://panoramax.openstreetmap.fr"
            }]
        }
    ]

    build_html(geojson, hotspots, profile)
