import math
import io
import httpx
import numpy as np
from PIL import Image
from pathlib import Path

ARCGIS_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"


def _lat_lon_to_tile(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    n = 2 ** zoom
    x = int((lon + 180) / 360 * n)
    lat_rad = math.radians(lat)
    y = int((1 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2 * n)
    return x, y


def _tile_to_lat_lon(x: int, y: int, zoom: int) -> tuple[float, float, float, float]:
    n = 2 ** zoom
    lon_w = x / n * 360 - 180
    lon_e = (x + 1) / n * 360 - 180
    lat_n = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    lat_s = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return lat_s, lon_w, lat_n, lon_e


async def fetch_tiles_for_bbox(
    west: float, south: float, east: float, north: float, zoom: int = 18,
) -> dict:
    x_min, y_min = _lat_lon_to_tile(north, west, zoom)
    x_max, y_max = _lat_lon_to_tile(south, east, zoom)

    if x_max < x_min:
        x_min, x_max = x_max, x_min
    if y_max < y_min:
        y_min, y_max = y_max, y_min

    nx = x_max - x_min + 1
    ny = y_max - y_min + 1

    if nx * ny > 100:
        zoom = max(15, zoom - 2)
        x_min, y_min = _lat_lon_to_tile(north, west, zoom)
        x_max, y_max = _lat_lon_to_tile(south, east, zoom)
        if x_max < x_min:
            x_min, x_max = x_max, x_min
        if y_max < y_min:
            y_min, y_max = y_max, y_min
        nx = x_max - x_min + 1
        ny = y_max - y_min + 1

    if nx * ny > 400:
        step_x = max(1, nx // 10)
        step_y = max(1, ny // 10)
        x_max = x_min + 10 * step_x
        y_max = y_min + 10 * step_y
        nx = 11
        ny = 11

    tile_w, tile_h = 256, 256
    canvas = Image.new("RGB", (nx * tile_w, ny * tile_h), (0, 0, 0))

    async with httpx.AsyncClient(timeout=20.0) as client:
        for i, x in enumerate(range(x_min, x_max + 1)):
            for j, y in enumerate(range(y_min, y_max + 1)):
                url = ARCGIS_URL.format(z=zoom, y=y, x=x)
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        tile = Image.open(io.BytesIO(resp.content))
                        canvas.paste(tile, (i * tile_w, j * tile_h))
                except Exception:
                    pass

    lat_s, lon_w, lat_n, lon_e = _tile_to_lat_lon(x_min, y_min, zoom)
    lat_s2, lon_w2, lat_n2, lon_e2 = _tile_to_lat_lon(x_max, y_max, zoom)
    bbox_w = min(lon_w, lon_w2)
    bbox_s = min(lat_s, lat_s2)
    bbox_e = max(lon_e, lon_e2)
    bbox_n = max(lat_n, lat_n2)

    arr = np.array(canvas)
    return {
        "image": arr,
        "width": canvas.width,
        "height": canvas.height,
        "zoom": zoom,
        "bbox": [bbox_w, bbox_s, bbox_e, bbox_n],
        "n_tiles": nx * ny,
    }


def pixel_to_lonlat(px: int, py: int, img_w: int, img_h: int, bbox: list[float]) -> tuple[float, float]:
    lon = bbox[0] + (px / img_w) * (bbox[2] - bbox[0])
    lat = bbox[3] - (py / img_h) * (bbox[3] - bbox[1])
    return lat, lon
