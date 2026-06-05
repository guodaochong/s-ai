import json, httpx

print("=== S-AI Platform Running ===")
print()

print("[GIS] spatial_query: contains(Beijing, Tiananmen)")
r = httpx.post("http://127.0.0.1:5001/call_tool", json={"name": "spatial_query", "arguments": {"geometry_a": {"type": "Polygon", "coordinates": [[[116.2,39.7],[116.6,39.7],[116.6,40.1],[116.2,40.1],[116.2,39.7]]]}, "geometry_b": {"type": "Point", "coordinates": [116.397, 39.908]}, "relation": "contains"}})
print(f"  result: {r.json().get('result')}")

print("[GIS] buffer: 5km buffer around a point")
r = httpx.post("http://127.0.0.1:5001/call_tool", json={"name": "buffer", "arguments": {"geometry": {"type": "Point", "coordinates": [116.397, 39.908]}, "distance": 0.05}})
print(f"  result type: {r.json().get('geometry', {}).get('type')}")

print("[GIS] overlay: intersection of two polygons")
r = httpx.post("http://127.0.0.1:5001/call_tool", json={"name": "overlay", "arguments": {"geometry_a": {"type": "Polygon", "coordinates": [[[0,0],[2,0],[2,2],[0,2],[0,0]]]}, "geometry_b": {"type": "Polygon", "coordinates": [[[1,0],[3,0],[3,2],[1,2],[1,0]]]}, "operation": "intersection"}})
print(f"  result type: {r.json().get('geometry', {}).get('type')}")

print("[KNOWLEDGE] get_parameter: Manning n for HDPE pipe")
r = httpx.post("http://127.0.0.1:5003/call_tool", json={"name": "get_parameter", "arguments": {"parameter_name": "manning_n", "conditions": {"surface": "HDPE"}}})
results = r.json().get("results", [])
for e in results:
    print(f"  {e.get('surface')} {e.get('condition')}: n_typical={e.get('n_typical')}, range=[{e.get('n_min')}, {e.get('n_max')}]")

print("[KNOWLEDGE] get_parameter: Shenzhen design storm")
r = httpx.post("http://127.0.0.1:5003/call_tool", json={"name": "get_parameter", "arguments": {"parameter_name": "design_storm", "conditions": {"city": "shenzhen"}}})
results = r.json().get("results", [])
for e in results:
    print(f"  city={e.get('city')}: A1={e.get('A1')}, C={e.get('C')}, b={e.get('b')}, n={e.get('n')}")

print("[DATA] validate_data: check GeoJSON quality")
r = httpx.post("http://127.0.0.1:5002/call_tool", json={"name": "validate_data", "arguments": {"data": {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [116.4, 39.9]}, "properties": {"name": "test"}}]}, "checks": ["topology", "attributes", "crs"]}})
d = r.json()
print(f"  valid={d.get('is_valid')}, issues={d.get('issues_found')}")

print("[MAP] render_map: Beijing area polygon")
r = httpx.post("http://127.0.0.1:5004/call_tool", json={"name": "render_map", "arguments": {"layers": [{"data": {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[116.3,39.9],[116.4,39.9],[116.4,40.0],[116.3,40.0],[116.3,39.9]]]}, "properties": {}}]}, "style": {"color": "blue", "alpha": 0.3}}], "title": "Beijing Area"}})
d = r.json()
img_len = len(d.get("image_base64", ""))
print(f"  image size: ~{img_len * 3 // 4 // 1024}KB PNG")

print()
print("=== All 4 MCP Servers Working ===")
