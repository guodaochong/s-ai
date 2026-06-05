import json
import sys

import httpx

BASE = "http://127.0.0.1:5001/call_tool"


def call_gis(tool_name: str, arguments: dict) -> dict:
    resp = httpx.post(BASE, json={"name": tool_name, "arguments": arguments}, timeout=30)
    return resp.json()


print("=" * 60)
print("  S-AI 功能演示 - MCP GIS 工具调用")
print("=" * 60)

# 1. geometry_properties: 计算一个多边形的属性
print("\n[1] geometry_properties - 计算几何属性")
result = call_gis("geometry_properties", {
    "geometry": {
        "type": "Polygon",
        "coordinates": [[[116.3, 39.9], [116.4, 39.9], [116.4, 40.0], [116.3, 40.0], [116.3, 39.9]]]
    }
})
print(f"  结果: {json.dumps(result, indent=2, ensure_ascii=False)}")

# 2. buffer: 在一个点周围生成 0.01 度的缓冲区
print("\n[2] buffer - 生成缓冲区")
result = call_gis("buffer", {
    "geometry": {"type": "Point", "coordinates": [116.397, 39.908]},
    "distance": 0.01
})
geom_type = result.get("geometry", {}).get("type", "unknown")
print(f"  缓冲区类型: {geom_type}")

# 3. spatial_query: 判断点是否在多边形内
print("\n[3] spatial_query - 空间查询: 天安门是否在北京城区内?")
result = call_gis("spatial_query", {
    "geometry_a": {"type": "Polygon", "coordinates": [[[116.2, 39.7], [116.6, 39.7], [116.6, 40.1], [116.2, 40.1], [116.2, 39.7]]]},
    "geometry_b": {"type": "Point", "coordinates": [116.397, 39.908]},
    "relation": "contains"
})
print(f"  北京城区包含天安门: {result.get('result')}")

# 4. overlay: 两个多边形的交集
print("\n[4] overlay - 叠加分析: 两个区域交集")
result = call_gis("overlay", {
    "geometry_a": {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]},
    "geometry_b": {"type": "Polygon", "coordinates": [[[1, 0], [3, 0], [3, 2], [1, 2], [1, 0]]]},
    "operation": "intersection"
})
print(f"  交集几何类型: {result.get('geometry', {}).get('type')}")

# 5. validate_data: 数据质量检查
print("\n[5] validate_data - 数据质量检查")
result = call_gis("validate_data", {
    "data": {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [116.4, 39.9]}, "properties": {"name": "test1"}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [116.5, 39.95]}, "properties": {}},
        ]
    },
    "checks": ["topology", "attributes", "crs"]
})
print(f"  有效: {result.get('is_valid')}, 问题数: {result.get('issues_found')}")
for issue in result.get("issues", []):
    print(f"    - {issue}")

print("\n" + "=" * 60)

# Test Knowledge server
print("\n[6] Knowledge - 查询曼宁糙率参数")
resp = httpx.post("http://127.0.0.1:5003/call_tool", json={
    "name": "get_parameter",
    "arguments": {"parameter_name": "manning_n", "conditions": {"surface": "混凝土管道"}}
}, timeout=30)
result = resp.json()
entries = result.get("results", [])
if entries:
    for e in entries:
        print(f"  {e.get('surface', '')} / {e.get('condition', '')}: n = {e.get('n_typical')} (范围 {e.get('n_min')}-{e.get('n_max')})")
else:
    print(f"  结果: {json.dumps(result, indent=2, ensure_ascii=False)}")

print("\n[7] Knowledge - 查询暴雨强度公式")
resp = httpx.post("http://127.0.0.1:5003/call_tool", json={
    "name": "get_parameter",
    "arguments": {"parameter_name": "design_storm", "conditions": {"city": "北京"}}
}, timeout=30)
result = resp.json()
entries = result.get("results", [])
if entries:
    for e in entries:
        print(f"  {e.get('city')}: q = 167×{e.get('A1')}×(1+{e.get('C')}×lgP)/({e.get('b')})^({e.get('n')})")

print("\n" + "=" * 60)
print("  所有功能测试完成!")
print("=" * 60)
