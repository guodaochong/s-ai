def compute_xxx(**kwargs):
    center_lat = kwargs.get('center_lat', 33.19)
    center_lon = kwargs.get('center_lon', 104.89)
    radius_km = kwargs.get('radius_km', 1)
    num_points = kwargs.get('num_points', 8)
    
    # Convert radius to degrees (approximate)
    radius_deg = radius_km / 111.32
    
    # Generate random points within the radius
    np.random.seed(42)
    angles = np.random.uniform(0, 2*np.pi, num_points)
    distances = np.random.uniform(0, radius_deg, num_points)
    
    lons = center_lon + distances * np.cos(angles) / np.cos(np.radians(center_lat))
    lats = center_lat + distances * np.sin(angles)
    
    # Create points list
    points = []
    for i, (lon, lat) in enumerate(zip(lons, lats)):
        points.append({
            "lat": float(lat),
            "lng": float(lon),
            "label": f"Station {i+1}"
        })
    
    # Prepare points for Voronoi computation
    coords = np.column_stack((lons, lats))
    
    # Add points at infinity to ensure bounded Voronoi cells
    far_point = radius_deg * 10
    extra_points = [
        [center_lon - far_point, center_lat - far_point],
        [center_lon + far_point, center_lat - far_point],
        [center_lon - far_point, center_lat + far_point],
        [center_lon + far_point, center_lat + far_point]
    ]
    all_points = np.vstack((coords, extra_points))
    
    # Compute Voronoi diagram
    vor = scipy.spatial.Voronoi(all_points)
    
    # Process Voronoi regions
    features = []
    data_points = []
    
    for i in range(num_points):
        region_idx = vor.point_region[i]
        region = vor.regions[region_idx]
        
        # Skip regions with -1 (unbounded)
        if -1 in region:
            continue
            
        # Get vertices of the region
        polygon = [vor.vertices[v] for v in region]
        
        # Clip vertices to valid range
        polygon = [
            [max(-180, min(180, lon)), max(-90, min(90, lat))]
            for lon, lat in polygon
        ]
        
        # Create GeoJSON feature
        features.append({
            "type": "Feature",
            "properties": {"label": f"Station {i+1}"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [polygon]
            }
        })
        
        # Add to data points
        data_points.append({
            "x": float(lons[i]),
            "y": float(lats[i]),
            "label": f"Station {i+1}"
        })
    
    # Create table data
    table = [{"Station": f"Station {i+1}", "Latitude": lats[i], "Longitude": lons[i]} 
             for i in range(num_points)]
    
    return {
        "geojson": {
            "type": "FeatureCollection",
            "features": features
        },
        "points": points,
        "data_points": data_points,
        "table": table,
        "chart_type": "scatter"
    }