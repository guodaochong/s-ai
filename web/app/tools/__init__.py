from __future__ import annotations

import json
import re
import time

import structlog

from app.config import GEN_TOOL_DIR, GLM_CODE_URL, MODEL_CODE, logger
from app.llm import call_llm

_CODE_TEMPLATES: list[tuple[str, str]] = [
    (r"六边形|蜂巢网格|honeycomb", r'''
def compute_honeycomb_grid(**kwargs):
    import math
    center_lat = kwargs.get('center_lat', 33.19)
    center_lng = kwargs.get('center_lng', 104.89)
    radius_m = kwargs.get('radius_m', kwargs.get('radius_km', 1) * 1000 if kwargs.get('radius_km') else 1000)
    cell_size = kwargs.get('cell_size', kwargs.get('size', 100))
    lat_rad = center_lat * math.pi / 180
    dlat = cell_size * math.sqrt(3) / 110540.0
    dlng = cell_size * 1.5 / (111320.0 * math.cos(lat_rad))
    cols = int(2 * radius_m / (cell_size * 1.5)) + 1
    rows = int(2 * radius_m / (cell_size * math.sqrt(3))) + 1
    features = []
    for q in range(-cols // 2, cols // 2 + 1):
        for r in range(-rows // 2, rows // 2 + 1):
            cx = cell_size * 1.5 * q
            cy = cell_size * math.sqrt(3) * (r + q / 2.0)
            if math.sqrt(cx * cx + cy * cy) > radius_m:
                continue
            lng = center_lng + cx / (111320.0 * math.cos(lat_rad))
            lat = center_lat + cy / 110540.0
            coords = []
            for i in range(6):
                angle = math.pi / 3 * i
                hx = cx + cell_size * math.cos(angle)
                hy = cy + cell_size * math.sin(angle)
                coords.append([round(center_lng + hx / (111320 * math.cos(lat_rad)), 8), round(center_lat + hy / 110540, 8)])
            coords.append(coords[0])
            features.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [coords]}, "properties": {"cell_id": f"H{q}_{r}", "center_lat": round(lat, 6), "center_lng": round(lng, 6)}})
    geojson = {"type": "FeatureCollection", "features": features}
    return {"geojson": geojson, "total_cells": len(features), "cell_size_m": cell_size, "center": {"lat": center_lat, "lng": center_lng}, "radius_m": radius_m}
'''),
    (r"矩形网格|渔网|grid.*rect", r'''
def compute_rectangular_grid(**kwargs):
    import math
    center_lat = kwargs.get('center_lat', 33.19)
    center_lng = kwargs.get('center_lng', 104.89)
    radius_m = kwargs.get('radius_m', 1000)
    cell_size = kwargs.get('cell_size', kwargs.get('size', 200))
    lat_rad = center_lat * math.pi / 180
    half_lat = radius_m / 110540.0
    half_lng = radius_m / (111320.0 * math.cos(lat_rad))
    dlat = cell_size / 110540.0
    dlng = cell_size / (111320.0 * math.cos(lat_rad))
    features = []
    row = 0
    lat = center_lat - half_lat
    while lat <= center_lat + half_lat:
        col = 0
        lng = center_lng - half_lng
        while lng <= center_lng + half_lng:
            coords = [[round(lng, 8), round(lat, 8)], [round(lng + dlng, 8), round(lat, 8)], [round(lng + dlng, 8), round(lat + dlat, 8)], [round(lng, 8), round(lat + dlat, 8)], [round(lng, 8), round(lat, 8)]]
            features.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [coords]}, "properties": {"cell_id": f"R{row}_{col}", "row": row, "col": col}})
            col += 1
            lng += dlng
        row += 1
        lat += dlat
    geojson = {"type": "FeatureCollection", "features": features}
    return {"geojson": geojson, "total_cells": len(features), "cell_size_m": cell_size, "rows": row, "cols": col if row > 0 else 0}
'''),
    (r"圆.*缓冲|buffer.*circle|圆形缓冲", r'''
def compute_circle_buffer(**kwargs):
    import math
    center_lat = kwargs.get('center_lat', 33.19)
    center_lng = kwargs.get('center_lng', 104.89)
    radius_m = kwargs.get('radius_m', kwargs.get('radius_km', 1) * 1000 if kwargs.get('radius_km') else 1000)
    lat_rad = center_lat * math.pi / 180
    steps = kwargs.get('steps', 64)
    coords = []
    for i in range(steps):
        angle = 2 * math.pi * i / steps
        lng = center_lng + radius_m * math.cos(angle) / (111320 * math.cos(lat_rad))
        lat = center_lat + radius_m * math.sin(angle) / 110540.0
        coords.append([round(lng, 8), round(lat, 8)])
    coords.append(coords[0])
    area_km2 = math.pi * (radius_m / 1000) ** 2
    geojson = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [coords]}, "properties": {"radius_m": radius_m, "area_km2": round(area_km2, 4), "center_lat": center_lat, "center_lng": center_lng}}]}
    return {"geojson": geojson, "area_km2": round(area_km2, 4), "radius_m": radius_m, "center": {"lat": center_lat, "lng": center_lng}}
'''),
    (r"环形|同心圆|ring|concentric", r'''
def compute_concentric_rings(**kwargs):
    import math
    center_lat = kwargs.get('center_lat', 33.19)
    center_lng = kwargs.get('center_lng', 104.89)
    radii = kwargs.get('radii', kwargs.get('radius_list', [200, 500]))
    if isinstance(radii, (int, float)):
        radii = [radii]
    lat_rad = center_lat * math.pi / 180
    features = []
    for idx, r in enumerate(radii):
        coords = []
        for i in range(64):
            angle = 2 * math.pi * i / 64
            lng = center_lng + r * math.cos(angle) / (111320 * math.cos(lat_rad))
            lat = center_lat + r * math.sin(angle) / 110540.0
            coords.append([round(lng, 8), round(lat, 8)])
        coords.append(coords[0])
        prev_r = radii[idx - 1] if idx > 0 else 0
        area_km2 = math.pi * ((r / 1000) ** 2 - (prev_r / 1000) ** 2)
        features.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [coords]}, "properties": {"ring": idx + 1, "radius_m": r, "inner_radius_m": prev_r, "area_km2": round(area_km2, 4)}})
    geojson = {"type": "FeatureCollection", "features": features}
    return {"geojson": geojson, "rings": len(features), "radii_m": radii}
'''),
    (r"随机.*点|random.*point|撒点", r'''
def compute_random_points(**kwargs):
    import math
    import numpy as np
    center_lat = kwargs.get('center_lat', 33.19)
    center_lng = kwargs.get('center_lng', 104.89)
    radius_m = kwargs.get('radius_m', 1000)
    num_points = kwargs.get('num_points', kwargs.get('n', 20))
    seed = kwargs.get('seed', 42)
    lat_rad = center_lat * math.pi / 180
    dlat = radius_m / 110540.0
    dlng = radius_m / (111320 * math.cos(lat_rad))
    np.random.seed(seed)
    pts = []
    for _ in range(num_points):
        r = radius_m * math.sqrt(np.random.random())
        theta = np.random.uniform(0, 2 * math.pi)
        lng = center_lng + r * math.cos(theta) / (111320 * math.cos(lat_rad))
        lat = center_lat + r * math.sin(theta) / 110540.0
        pts.append({"lat": round(lat, 6), "lng": round(lng, 6)})
    geojson = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [p["lng"], p["lat"]]}, "properties": {"id": i}} for i, p in enumerate(pts)]}
    return {"geojson": geojson, "total_points": len(pts), "center": {"lat": center_lat, "lng": center_lng}, "radius_m": radius_m}
'''),
    (r"扇形|sector", r'''
def compute_sector(**kwargs):
    import math
    center_lat = kwargs.get('center_lat', 33.19)
    center_lng = kwargs.get('center_lng', 104.89)
    radius_m = kwargs.get('radius_m', 500)
    start_angle = kwargs.get('start_angle', 0)
    end_angle = kwargs.get('end_angle', 90)
    num_sectors = kwargs.get('num_sectors', 1)
    lat_rad = center_lat * math.pi / 180
    features = []
    if num_sectors <= 1:
        sector_ranges = [(start_angle, end_angle)]
    else:
        step = (end_angle - start_angle) / num_sectors
        sector_ranges = [(start_angle + i * step, start_angle + (i + 1) * step) for i in range(num_sectors)]
    for idx, (sa, ea) in enumerate(sector_ranges):
        coords = [[round(center_lng, 8), round(center_lat, 8)]]
        for a in range(int(sa * 10), int(ea * 10) + 1):
            angle = a / 10.0 * math.pi / 180.0
            lng = center_lng + radius_m * math.cos(angle) / (111320 * math.cos(lat_rad))
            lat = center_lat + radius_m * math.sin(angle) / 110540.0
            coords.append([round(lng, 8), round(lat, 8)])
        coords.append([round(center_lng, 8), round(center_lat, 8)])
        features.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [coords]}, "properties": {"sector": idx + 1, "start_deg": round(sa, 1), "end_deg": round(ea, 1), "radius_m": radius_m}})
    geojson = {"type": "FeatureCollection", "features": features}
    return {"geojson": geojson, "sectors": len(features)}
'''),
    (r"星形|star.*polygon", r'''
def compute_star_polygon(**kwargs):
    import math
    center_lat = kwargs.get('center_lat', 33.19)
    center_lng = kwargs.get('center_lng', 104.89)
    outer_r = kwargs.get('outer_radius_m', kwargs.get('radius_m', 500))
    inner_r = kwargs.get('inner_radius_m', outer_r * 0.4)
    points = kwargs.get('points', kwargs.get('tips', 5))
    lat_rad = center_lat * math.pi / 180
    coords = []
    for i in range(points * 2):
        angle = math.pi * i / points - math.pi / 2
        r = outer_r if i % 2 == 0 else inner_r
        lng = center_lng + r * math.cos(angle) / (111320 * math.cos(lat_rad))
        lat = center_lat + r * math.sin(angle) / 110540.0
        coords.append([round(lng, 8), round(lat, 8)])
    coords.append(coords[0])
    geojson = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [coords]}, "properties": {"tips": points, "outer_radius_m": outer_r, "inner_radius_m": round(inner_r, 1)}}]}
    return {"geojson": geojson, "tips": points}
'''),
    (r"螺旋|spiral", r'''
def compute_spiral(**kwargs):
    import math
    center_lat = kwargs.get('center_lat', 33.19)
    center_lng = kwargs.get('center_lng', 104.89)
    max_radius_m = kwargs.get('radius_m', kwargs.get('max_radius_m', 500))
    turns = kwargs.get('turns', 3)
    points_per_turn = kwargs.get('points_per_turn', 36)
    lat_rad = center_lat * math.pi / 180
    coords = []
    total_pts = turns * points_per_turn
    for i in range(total_pts + 1):
        t = i / total_pts
        angle = 2 * math.pi * turns * t
        r = max_radius_m * t
        lng = center_lng + r * math.cos(angle) / (111320 * math.cos(lat_rad))
        lat = center_lat + r * math.sin(angle) / 110540.0
        coords.append([round(lng, 8), round(lat, 8)])
    geojson = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords}, "properties": {"turns": turns, "max_radius_m": max_radius_m}}]}
    return {"geojson": geojson, "turns": turns, "points": len(coords)}
'''),
    (r"渠道|梯形|矩形.*水力|manning.*channel|hydraulics", r'''
def compute_channel_hydraulics(**kwargs):
    import math
    shape = kwargs.get('shape', 'trapezoidal')
    b = kwargs.get('bottom_width', kwargs.get('b', 3.0))
    m = kwargs.get('side_slope', kwargs.get('m', 1.5))
    S = kwargs.get('slope', kwargs.get('S', 0.001))
    n = kwargs.get('manning_n', kwargs.get('n', 0.025))
    Q = kwargs.get('flow_rate', kwargs.get('Q', kwargs.get('flow_cms', 15.0)))
    def xsec(h):
        if shape == 'rectangular':
            return b * h, b + 2 * h, b
        return (b + m * h) * h, b + 2 * h * math.sqrt(1 + m * m), b + 2 * m * h
    h_low, h_high = 0.01, 50.0
    for _ in range(100):
        h_mid = (h_low + h_high) / 2
        A, P, _ = xsec(h_mid)
        R = A / P if P > 0 else 0
        Q_calc = (1.0 / n) * A * R ** (2.0 / 3.0) * math.sqrt(S)
        if Q_calc < Q:
            h_low = h_mid
        else:
            h_high = h_mid
    h = (h_low + h_high) / 2
    A, P, T = xsec(h)
    R = A / P if P > 0 else 0
    V = Q / A if A > 0 else 0
    Fr = V / math.sqrt(9.81 * A / T) if T > 0 and A > 0 else 0
    return {"depth_m": round(h, 4), "velocity_ms": round(V, 4), "area_m2": round(A, 4), "wetted_perimeter_m": round(P, 4), "hydraulic_radius_m": round(R, 4), "froude_number": round(Fr, 3), "flow_regime": "critical" if 0.9 < Fr < 1.1 else ("supercritical" if Fr >= 1.1 else "subcritical"), "flow_rate_cms": Q, "shape": shape}
'''),
    (r"推理公式|rational.*method", r'''
def compute_rational_method(**kwargs):
    import math
    area_km2 = kwargs.get('area_km2', 10.0)
    rainfall_mm = kwargs.get('rainfall_mm', kwargs.get('rainfall_intensity_mmh', 50.0))
    runoff_coeff = kwargs.get('runoff_coeff', kwargs.get('C', 0.6))
    concentration_min = kwargs.get('concentration_min', 60)
    Q = 0.278 * runoff_coeff * rainfall_mm * area_km2 / (concentration_min / 60.0)
    vol_m3 = Q * concentration_min * 60
    return {"peak_flow_Q_cms": round(Q, 2), "runoff_coeff": runoff_coeff, "area_km2": area_km2, "rainfall_mm": rainfall_mm, "concentration_min": concentration_min, "runoff_volume_m3": round(vol_m3), "method": "推理公式法"}
'''),
    (r"暴雨强度|rainfall.*intensity|暴雨.*公式|design.*storm", r'''
def compute_design_storm(**kwargs):
    import math
    P = kwargs.get('return_period', kwargs.get('P', 50))
    t = kwargs.get('duration_min', kwargs.get('t', 60))
    A1 = kwargs.get('A1', 10.0)
    C = kwargs.get('C', 0.5)
    b = kwargs.get('b', 20.0)
    n_exp = kwargs.get('n_exp', 0.8)
    q = 167 * A1 * (1 + C * math.log10(P)) / (t + b)**n_exp
    total_mm = q * t / 60.0
    Chicago = []
    r_ratio = kwargs.get('r_ratio', 0.4)
    for i in range(1, int(t) + 1):
        if i <= r_ratio * t:
            intensity = q * (r_ratio * t / i)**0.5
        else:
            intensity = q * ((1 - r_ratio) * t / (t - i + 1))**0.5
        Chicago.append({"time_min": i, "intensity_mmh": round(intensity, 2)})
    return {"peak_intensity_mmh": round(q, 2), "total_rainfall_mm": round(total_mm, 1), "return_period_yr": P, "duration_min": t, "Chicago_pattern": Chicago[:24], "method": "暴雨强度公式"}
'''),
    (r"voronoi|泰森|thiessen", r'''
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
'''),
]


def try_template(query: str) -> str | None:
    for pattern, code in _CODE_TEMPLATES:
        if re.search(pattern, query, re.IGNORECASE):
            return code
    return None


_LAZY_PATTERNS = re.compile(
    r'简化[版]?'
    r'|仅返回'
    r'|TODO|FIXME'
    r'|实际需要.*更复杂'
    r'|这里仅'
    r'|简化处理'
    r'|省略了|略去',
    re.IGNORECASE
)

_GEOJSON_GEOM_TYPES = {"Polygon", "MultiPolygon", "LineString", "MultiLineString"}


def check_code_quality(code: str, query: str) -> list[str]:
    issues = []
    if _LAZY_PATTERNS.search(code):
        issues.append("代码包含简化/偷懒标记")
    fn_sig = re.search(r'def\s+\w+\s*\(([^)]*)\)', code)
    if fn_sig:
        params = fn_sig.group(1).strip()
        if params and not params.startswith('**'):
            issues.append(f"函数签名错误: def xxx({params}) → 必须是 def xxx(**kwargs)")
    if re.search(r'多边|polygon|网格|网格划分', query, re.IGNORECASE):
        if 'Polygon' not in code:
            issues.append("查询要求多边形但代码不含Polygon")
    return issues


def check_result_quality(result: dict, query: str) -> list[str]:
    issues = []
    if isinstance(result, dict) and "error" in result:
        return [f"执行错误: {result['error'][:100]}"]
    if re.search(r'多边|polygon|网格|泰森|voronoi', query, re.IGNORECASE):
        geojson = result.get("geojson", {})
        if isinstance(geojson, dict):
            for f in geojson.get("features", [])[:3]:
                geom = f.get("geometry", {})
                if geom.get("type") not in _GEOJSON_GEOM_TYPES:
                    issues.append(f"几何类型错误: {geom.get('type')} → 应为Polygon")
                    break
    return issues


async def generate_tool(query: str) -> dict | None:
    t0 = time.time()
    logger.info("[GenTool] >>> generating tool", query=query[:100], model=MODEL_CODE)
    messages = [
        {"role": "system", "content": """为水利空间智能平台生成一个Python函数。
严格规则：
1. 函数签名必须是 def compute_xxx(**kwargs): 参数必须用**kwargs
2. 函数内用 kwargs.get('参数名', 默认值) 读取参数，不要写死
3. 必须完整实现算法，禁止"简化版""TODO""近似"
4. geojson必须是Polygon/LineString，多边形坐标必须闭合(首尾坐标相同)
5. 只输出代码，不要import，不要解释

返回dict含计算结果，适合可视化时加对应字段：
- GeoJSON: "geojson": {"type":"FeatureCollection","features":[...]}
- 曲线: "data_points": [{"x":..., "y":..., "label":...}]
- 柱状图: "data_points" + "chart_type":"bar"
- 坐标: "points": [{"lat":..., "lng":..., "label":...}]
- 表格: "table": [{"col1": val, ...}]

可用: math, json, numpy(np), scipy.spatial.Voronoi。

经纬度与米转换(关键！):
- dx_meters → dlng: dlng = dx / (111320 * cos(lat_rad))
- dy_meters → dlat: dlat = dy / 110540
- lat_rad = lat * math.pi / 180
- 两点距离: haversine或简算 dx=dlng*111320*cos(lat_rad), dy=dlat*110540

算法参考(必须完整实现):
- 六边形网格: 轴坐标(q,r), flat-top: x=size*(3/2*q), y=size*(sqrt(3)*(r+q/2))。转经纬度: lng+=dx/(111320*cos(lat_rad)), lat+=dy/110540
- Voronoi泰森多边形:
  1. 生成N个随机点 np.random.seed(seed); points=np.column_stack([lngs, lats])
  2. vor=scipy.spatial.Voronoi(points)
  3. 遍历vor.regions, 跳过含-1的(无界区域)
  4. 用vor.vertices提取多边形顶点
  5. 用bbox裁剪: vertices[:,0]=np.clip(vertices[:,0],min_lng,max_lng)
  6. 闭合多边形: polygon.append(polygon[0])
  7. 面积: 用shoelace公式计算经纬度多边形面积(转米后计算)
  8. 输出: geojson含Polygon features, properties含station_id, area_km2
  重要: points必须是np.array([[lng1,lat1],[lng2,lat2],...])格式，不要用column_stack
  重要: vor.vertices已经是经纬度坐标，不需要额外转换
  示例: points_arr = np.array([[lng1,lat1],[lng2,lat2],...]); vor = Voronoi(points_arr)
- 缓冲区/圆: for angle in range(0,360,dstep): lng=clng+radius*cos(a)/(111320*cos(lat_rad)); lat=clat+radius*sin(a)/110540"""},
        {"role": "user", "content": query},
    ]
    try:
        content, _, _ = await call_llm(messages, model=MODEL_CODE, use_tools=False, max_tokens_override=4096, http_timeout=120.0, api_url=GLM_CODE_URL)
        code = content.strip()
        if code.startswith("```"):
            code = re.sub(r'^```\w*\n?', '', code)
            code = re.sub(r'\n?```$', '', code)
        code = re.sub(r'^(import\s+.+|from\s+.+import\s+.+)\n?', '', code, flags=re.MULTILINE)
        elapsed = int((time.time() - t0) * 1000)
        logger.info("[GenTool] <<< generated", elapsed_ms=elapsed, code_len=len(code))
        if not code.strip() or len(code) < 30:
            logger.warning("[GenTool] code too short", code_len=len(code))
            return None
        return {"code": code, "tool_name": _extract_tool_name(code)}
    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        logger.error("[GenTool] <<< generation failed", elapsed_ms=elapsed, error=str(e)[:200])
        return None


def _extract_tool_name(code: str) -> str:
    m = re.search(r'def\s+(compute_\w+)', code)
    return m.group(1) if m else f"gen_tool_{int(time.time())}"


async def generate_tool_with_retry(query: str, max_attempts: int = 5) -> tuple[dict | None, dict | None, list[str]]:
    logger.info("[GenRetry] >>> start", query=query[:80], max_attempts=max_attempts)

    template_code = try_template(query)
    if template_code:
        tool_name = _extract_tool_name(template_code)
        logger.info("[GenRetry] using template", tool=tool_name)
        result, err = _exec_code(tool_name, template_code, {})
        if result and not (isinstance(result, dict) and "error" in result):
            return {"code": template_code, "tool_name": tool_name, "_source": "template"}, result, []
        logger.warning("[GenRetry] template execution failed, falling back to LLM", error=str(err)[:100] if err else "")

    all_issues: list[str] = []
    for attempt in range(1, max_attempts + 1):
        logger.info("[GenRetry] attempt", attempt=attempt, max=max_attempts)
        gen = await generate_tool(query)
        if not gen:
            all_issues.append(f"attempt {attempt}: generation failed")
            continue

        code, tool_name = gen["code"], gen["tool_name"]
        quality = check_code_quality(code, query)
        if quality:
            all_issues.extend([f"attempt {attempt}: {q}" for q in quality])
            logger.warning("[GenRetry] code quality issues", attempt=attempt, issues=quality)
            continue

        result, err = _exec_code(tool_name, code, {})
        if result and not (isinstance(result, dict) and "error" in result):
            rq = check_result_quality(result, query)
            if not rq:
                logger.info("[GenRetry] <<< success", attempt=attempt, tool=tool_name)
                return gen, result, all_issues
            all_issues.extend([f"attempt {attempt}: {r}" for r in rq])
            logger.warning("[GenRetry] result quality issues", attempt=attempt, issues=rq)
        else:
            err_msg = result.get("error", str(err)) if isinstance(result, dict) else str(err)
            all_issues.append(f"attempt {attempt}: execution error: {str(err_msg)[:100]}")
            logger.warning("[GenRetry] execution error", attempt=attempt, error=str(err_msg)[:100])

    logger.error("[GenRetry] <<< all attempts failed", total_attempts=max_attempts)
    return None, None, all_issues


def _exec_code(tool_name: str, code: str, args: dict) -> tuple[dict | None, Exception | None]:
    safe_globals = {
        "__builtins__": __builtins__,
        "math": __import__("math"),
        "json": __import__("json"),
        "np": __import__("numpy"),
        "Voronoi": __import__("scipy").spatial.Voronoi,
    }
    safe_locals: dict = {}
    try:
        exec(code, safe_globals, safe_locals)
    except Exception as e:
        return {"error": f"Code exec error: {str(e)[:200]}"}, e
    fn = safe_locals.get(tool_name)
    if not fn:
        return {"error": f"Function {tool_name} not found"}, None
    try:
        result = fn(**args)
    except TypeError:
        try:
            result = fn(args)
        except TypeError:
            result = fn()
    return result if isinstance(result, dict) else {"result": str(result)}, None


def delete_generated(tool_name: str):
    path = GEN_TOOL_DIR / f"{tool_name}.py"
    if path.exists():
        path.unlink()
        logger.info("[GenTool] deleted", tool=tool_name)


def exec_generated(tool_name: str, args: dict) -> dict:
    import time as _t
    t0 = _t.time()
    path = GEN_TOOL_DIR / f"{tool_name}.py"
    if not path.exists():
        return {"error": f"Tool file not found: {tool_name}"}
    code = path.read_text(encoding="utf-8")
    safe_globals = {
        "__builtins__": __builtins__,
        "math": __import__("math"), "json": __import__("json"),
        "np": __import__("numpy"), "numpy": __import__("numpy"),
        "Voronoi": __import__("scipy").spatial.Voronoi,
        "base64": __import__("base64"),
    }
    safe_locals: dict = {}
    try:
        exec(code, safe_globals, safe_locals)
        fn = safe_locals.get(tool_name)
        if not fn:
            logger.error("[ExecGen] function not found after exec", tool=tool_name, locals_keys=list(safe_locals.keys()))
            return {"error": f"Function {tool_name} not found in generated code"}
        try:
            result = fn(**args)
        except TypeError:
            try:
                result = fn(args)
            except TypeError:
                result = fn()
        elapsed = int((_t.time() - t0) * 1000)
        if isinstance(result, dict) and "error" in result:
            logger.error("[ExecGen] <<< execution returned error", tool=tool_name, elapsed_ms=elapsed, error=result["error"][:100])
        else:
            r_keys = list(result.keys()) if isinstance(result, dict) else []
            logger.info("[ExecGen] <<< execution success", tool=tool_name, elapsed_ms=elapsed, result_keys=r_keys)
        return result if isinstance(result, dict) else {"result": str(result)}
    except Exception as e:
        elapsed = int((_t.time() - t0) * 1000)
        logger.error("[ExecGen] <<< exception", tool=tool_name, elapsed_ms=elapsed, error=f"{type(e).__name__}: {str(e)[:200]}")
        return {"error": f"Execution error: {str(e)[:200]}"}
