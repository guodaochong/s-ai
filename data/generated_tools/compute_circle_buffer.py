
def compute_circle_buffer(**kwargs):
    import math, json
    center_lng = kwargs.get('center_lng', 104.89)
    center_lat = kwargs.get('center_lat', 33.19)
    radius_m = kwargs.get('radius_m', 1000)
    segments = kwargs.get('segments', 64)
    lat_rad = math.radians(center_lat)
    coords = []
    for i in range(segments + 1):
        angle = 2 * math.pi * i / segments
        dx = radius_m * math.cos(angle)
        dy = radius_m * math.sin(angle)
        lng = center_lng + dx / (111320 * math.cos(lat_rad))
        lat = center_lat + dy / 110540
        coords.append([lng, lat])
    geojson = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [coords]}, "properties": {"radius_m": radius_m, "center": [center_lng, center_lat]}}]}
    return {"geojson": geojson, "area_km2": round(math.pi * (radius_m/1000)**2, 4), "radius_m": radius_m}
