def compute_voronoi_polygons(**kwargs):
    center_lat = kwargs.get('center_lat', 33.19)
    center_lon = kwargs.get('center_lon', 104.89)
    radius_km = kwargs.get('radius_km', 1.0)
    num_stations = kwargs.get('num_stations', 8)
    
    # Convert radius from km to degrees (approximate)
    radius_deg = radius_km / 111.0  # Rough conversion: 1 degree ~ 111km
    
    # Generate random stations within radius
    np.random.seed(42)  # For reproducibility
    thetas = np.random.uniform(0, 2*math.pi, num_stations)
    radii = np.random.uniform(0, radius_deg, num_stations)
    
    lons = center_lon + radii * np.cos(thetas)
    lats = center_lat + radii * np.sin(thetas)
    
    # Create Voronoi diagram
    points = np.column_stack((lons, lats))
    vor = scipy.spatial.Voronoi(points)
    
    # Filter regions and clip vertices
    valid_regions = []
    for i, region_idx in enumerate(vor.point_region):
        region = vor.regions[region_idx]
        if -1 not in region and len(region) > 0:
            polygon = [vor.vertices[v] for v in region]
            # Clip vertices to valid range
            polygon = [[min(max(p[0], -180), 180), min(max(p[1], -90), 90)] for p in polygon]
            valid_regions.append({
                'coordinates': polygon,
                'label': f'Station {i+1}'
            })
    
    # Generate GeoJSON
    features = []
    for region in valid_regions:
        features.append({
            'type': 'Feature',
            'geometry': {
                'type': 'Polygon',
                'coordinates': [region['coordinates']]
            },
            'properties': {
                'label': region['label']
            }
        })
    
    geojson = {
        'type': 'FeatureCollection',
        'features': features
    }
    
    # Generate points data
    points_data = []
    for i in range(num_stations):
        points_data.append({
            'lat': lats[i],
            'lng': lons[i],
            'label': f'Station {i+1}'
        })
    
    # Generate curve data (distance from center)
    curve_data = []
    for i in range(num_stations):
        dist = math.sqrt((lats[i] - center_lat)**2 + (lons[i] - center_lon)**2) * 111.0
        curve_data.append({
            'x': i+1,
            'y': dist,
            'label': f'Station {i+1}'
        })
    
    # Generate bar chart data (area of each Voronoi cell)
    bar_data = []
    for i, region in enumerate(valid_regions):
        # Approximate area calculation
        coords = np.array(region['coordinates'])
        x = coords[:, 0]
        y = coords[:, 1]
        area = 0.5 * np.abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))
        bar_data.append({
            'value': area,
            'label': region['label']
        })
    
    return {
        'GeoJSON': {'geojson': geojson},
        'Points': {'points': points_data},
        'Curve': {'data_points': curve_data},
        'Bar chart': {
            'data_points': [b['value'] for b in bar_data],
            'chart_type': 'bar',
            'labels': [b['label'] for b in bar_data]
        },
        'Table': [{
            'Station': f'Station {i+1}',
            'Latitude': lats[i],
            'Longitude': lons[i],
            'Distance from center (km)': curve_data[i]['y']
        } for i in range(num_stations)]
    }