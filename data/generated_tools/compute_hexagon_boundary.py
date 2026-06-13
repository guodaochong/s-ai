def compute_hexagon_boundary(**kwargs):
    center_lat = kwargs.get('center_lat', 33.19)
    center_lng = kwargs.get('center_lng', 104.89)
    radius_meters = kwargs.get('radius_meters', 500)
    earth_radius = 6371000  # 地球半径，单位米

    def haversine(lat1, lng1, lat2, lng2):
        phi1, phi2 = np.radians(lat1), np.radians(lat2)
        delta_lambda = np.radians(lng2 - lng1)
        a = np.sin((phi2 - phi1) / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(delta_lambda / 2) ** 2
        return 2 * earth_radius * np.arcsin(np.sqrt(a))

    def move_point(lat, lng, distance, bearing):
        lat_rad, lng_rad = np.radians(lat), np.radians(lng)
        bearing_rad = np.radians(bearing)
        new_lat_rad = np.arcsin(np.sin(lat_rad) * np.cos(distance / earth_radius) + 
                               np.cos(lat_rad) * np.sin(distance / earth_radius) * np.cos(bearing_rad))
        new_lng_rad = lng_rad + np.arctan2(np.sin(bearing_rad) * np.sin(distance / earth_radius) * np.cos(lat_rad),
                                          np.cos(distance / earth_radius) - np.sin(lat_rad) * np.sin(new_lat_rad))
        return np.degrees(new_lat_rad), np.degrees(new_lng_rad)

    angles = [0, 60, 120, 180, 240, 300]
    vertices = []
    for angle in angles:
        new_lat, new_lng = move_point(center_lat, center_lng, radius_meters, angle)
        vertices.append([new_lng, new_lat])
    vertices.append(vertices[0])  # 闭合多边形

    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [vertices]
                },
                "properties": {}
            }
        ]
    }

    points = [{"lat": center_lat, "lng": center_lng, "label": "中心点"}]
    for i, vertex in enumerate(vertices[:-1]):
        points.append({"lat": vertex[1], "lng": vertex[0], "label": f"顶点{i+1}"})

    return {
        "geojson": geojson,
        "points": points,
        "table": [{"顶点": f"顶点{i+1}", "经度": vertices[i][0], "纬度": vertices[i][1]} for i in range(6)]
    }