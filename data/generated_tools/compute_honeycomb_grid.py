def compute_honeycomb_grid(**kwargs):
    center_lat = kwargs.get('center_lat', 33.19)
    center_lng = kwargs.get('center_lng', 104.89)
    radius = kwargs.get('radius', 500)
    precision = kwargs.get('precision', 6)
    
    # Earth radius in meters
    earth_radius = 6371000
    
    # Convert radius to degrees (approximate)
    lat_deg_per_m = 1 / 111320
    lng_deg_per_m = 1 / (111320 * np.cos(np.radians(center_lat)))
    
    # Calculate hexagon side length in degrees
    side_length_deg = radius * lat_deg_per_m
    
    # Calculate hexagon vertices
    vertices = []
    for i in range(6):
        angle_deg = 60 * i
        angle_rad = np.radians(angle_deg)
        x = center_lng + side_length_deg * np.cos(angle_rad)
        y = center_lat + side_length_deg * np.sin(angle_rad)
        vertices.append([x, y])
    
    # Close the polygon
    vertices.append(vertices[0])
    
    # Generate grid of hexagons
    hexagons = []
    rows = int(np.ceil(2 * radius / (side_length_deg * 111320)))
    cols = int(np.ceil(2 * radius / (side_length_deg * 111320 * np.cos(np.radians(center_lat)))))
    
    for row in range(-rows, rows + 1):
        for col in range(-cols, cols + 1):
            # Calculate offset from center
            offset_lat = row * side_length_deg * 1.5
            offset_lng = col * side_length_deg * np.sqrt(3) + (row % 2) * side_length_deg * np.sqrt(3) / 2
            
            # Create hexagon vertices
            hex_vertices = []
            for i in range(6):
                angle_deg = 60 * i
                angle_rad = np.radians(angle_deg)
                x = center_lng + offset_lng + side_length_deg * np.cos(angle_rad)
                y = center_lat + offset_lat + side_length_deg * np.sin(angle_rad)
                hex_vertices.append([x, y])
            
            # Close the polygon
            hex_vertices.append(hex_vertices[0])
            
            # Check if hexagon is within radius
            center_point = hex_vertices[0]
            distance = np.sqrt((center_point[0] - center_lng)**2 + (center_point[1] - center_lat)**2) * 111320
            if distance <= radius:
                hexagon = {
                    "type": "Feature",
                    "properties": {"row": row, "col": col},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [hex_vertices]
                    }
                }
                hexagons.append(hexagon)
    
    # Create GeoJSON FeatureCollection
    geojson = {
        "type": "FeatureCollection",
        "features": hexagons
    }
    
    # Create data points for visualization
    data_points = []
    for i, hexagon in enumerate(hexagons):
        center_point = hexagon['geometry']['coordinates'][0][0]
        data_points.append({
            "x": i,
            "y": i,
            "label": f"Hexagon {i}"
        })
    
    # Create points for visualization
    points = []
    for hexagon in hexagons:
        center_point = hexagon['geometry']['coordinates'][0][0]
        points.append({
            "lat": center_point[1],
            "lng": center_point[0],
            "label": f"Hexagon {hexagon['properties']['row']}_{hexagon['properties']['col']}"
        })
    
    # Create table for visualization
    table = []
    for hexagon in hexagons:
        center_point = hexagon['geometry']['coordinates'][0][0]
        table.append({
            "row": hexagon['properties']['row'],
            "col": hexagon['properties']['col'],
            "lat": center_point[1],
            "lng": center_point[0]
        })
    
    return {
        "geojson": geojson,
        "data_points": data_points,
        "chart_type": "bar",
        "points": points,
        "table": table
    }
