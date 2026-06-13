def compute_hydro_monitoring(**kwargs):
    center_lat = kwargs.get('center_lat', 33.19)
    center_lon = kwargs.get('center_lon', 104.89)
    radius_km = kwargs.get('radius_km', 1.0)
    num_stations = kwargs.get('num_stations', 8)
    
    # 
    radius_m = radius_km * 1000
    # 1111.32km
    lon_degree_to_m = 111320 * np.cos(np.radians(center_lat))
    lat_degree_to_m = 111132
    
    # 
    np.random.seed(42)  # 
    station_coords = []
    for _ in range(num_stations):
        # 
        r = radius_m * np.sqrt(np.random.random())
        theta = 2 * np.pi * np.random.random()
        dx = r * np.cos(theta)
        dy = r * np.sin(theta)
        
        # 
        lon_offset = dx / lon_degree_to_m
        lat_offset = dy / lat_degree_to_m
        
        station_coords.append([center_lon + lon_offset, center_lat + lat_offset])
    
    # Voronoi
    vor = scipy.spatial.Voronoi(station_coords)
    
    # GeoJSON
    features = []
    for i, region_idx in enumerate(vor.point_region):
        region = vor.regions[region_idx]
        if -1 not in region and len(region) > 0:
            polygon_coords = [vor.vertices[v] for v in region]
            if len(polygon_coords) >= 3:
                # 
                if not np.allclose(polygon_coords[0], polygon_coords[-1]):
                    polygon_coords = polygon_coords + [polygon_coords[0]]
                
                feature = {
                    "type": "Feature",
                    "properties": {"station_id": i+1},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [polygon_coords]
                    }
                }
                features.append(feature)
    
    # GeoJSON
    for i, coord in enumerate(station_coords):
        features.append({
            "type": "Feature",
            "properties": {"station_id": i+1, "type": "point"},
            "geometry": {
                "type": "Point",
                "coordinates": coord
            }
        })
    
    geojson = {
        "type": "FeatureCollection",
        "features": features
    }
    
    # 
    data_points = []
    for i, coord in enumerate(station_coords):
        data_points.append({
            "x": i+1,
            "y": np.linalg.norm(np.array(coord) - np.array([center_lon, center_lat])),
            "label": f"Station {i+1}"
        })
    
    return {
        "geojson": geojson,
        "data_points": data_points,
        "points": [{"lat": coord[1], "lng": coord[0], "label": f"Station {i+1}"} 
                  for i, coord in enumerate(station_coords)],
        "table": [{"station_id": i+1, "latitude": coord[1], "longitude": coord[0]} 
                 for i, coord in enumerate(station_coords)]
    }