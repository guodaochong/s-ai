
def compute_voronoi_tessellation(**kwargs):
    import math, json
    import numpy as np
    from scipy.spatial import Voronoi
    center_lat = kwargs.get('center_lat', 33.19)
    center_lng = kwargs.get('center_lng', 104.89)
    radius_m = kwargs.get('radius_m', kwargs.get('radius_km', 1) * 1000 if kwargs.get('radius_km') else 1000)
    num_stations = kwargs.get('num_stations', kwargs.get('stations', 8))
    seed = kwargs.get('seed', 42)
    lat_rad = center_lat * math.pi / 180
    dlat_deg = radius_m / 110540.0
    dlng_deg = radius_m / (111320.0 * math.cos(lat_rad))
    np.random.seed(seed)
    lats = center_lat + np.random.uniform(-dlat_deg, dlat_deg, num_stations)
    lngs = center_lng + np.random.uniform(-dlng_deg, dlng_deg, num_stations)
    points = np.column_stack([lngs, lats])
    vor = Voronoi(points)
    min_lng, max_lng = center_lng - dlng_deg, center_lng + dlng_deg
    min_lat, max_lat = center_lat - dlat_deg, center_lat + dlat_deg
    features = []
    for i in range(num_stations):
        region_idx = vor.point_region[i]
        region = vor.regions[region_idx]
        if -1 in region or len(region) < 3:
            theta = np.linspace(0, 2 * math.pi, 13)
            ring_lng = center_lng + (radius_m / num_stations) * np.cos(theta) / (111320 * math.cos(lat_rad))
            ring_lat = center_lat + (radius_m / num_stations) * np.sin(theta) / 110540.0
            coords = [[float(ring_lng[j]), float(ring_lat[j])] for j in range(len(theta))]
            area_m2 = math.pi * (radius_m / num_stations) ** 2
        else:
            verts = vor.vertices[region]
            verts[:, 0] = np.clip(verts[:, 0], min_lng, max_lng)
            verts[:, 1] = np.clip(verts[:, 1], min_lat, max_lat)
            coords = [[float(v[0]), float(v[1])] for v in verts]
            coords.append(coords[0])
            dx = np.diff([c[0] for c in coords]) * 111320 * math.cos(lat_rad)
            dy = np.diff([c[1] for c in coords]) * 110540
            area_m2 = 0.5 * abs(sum(dx[j] * dy[j] for j in range(len(dx))))
        features.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [coords]}, "properties": {"station_id": i, "lng": round(float(lngs[i]), 6), "lat": round(float(lats[i]), 6), "area_km2": round(area_m2 / 1e6, 4)}})
    geojson = {"type": "FeatureCollection", "features": features}
    total_area = sum(f["properties"]["area_km2"] for f in features)
    return {"geojson": geojson, "total_stations": num_stations, "total_area_km2": round(total_area, 4), "center": {"lat": center_lat, "lng": center_lng}, "radius_m": radius_m}
