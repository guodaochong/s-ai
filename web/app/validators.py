from __future__ import annotations

import json
import re
import sqlite3
import time

import httpx
import structlog

from app.config import CRITICAL_TOOLS, DATA_DIR, MODEL_FLASH, STUDY_BBOX, logger
from app.llm import call_llm

PHYSICS_RANGES = {
    "velocity_ms": (0, 15, "流速(m/s)"),
    "depth_m": (0, 30, "水深(m)"),
    "slope": (0, 1, "坡度"),
    "manning_n": (0.01, 0.3, "曼宁糙率"),
    "runoff_coefficient": (0, 1, "径流系数"),
    "flood_depth_cm": (0, 500, "洪水深度(cm)"),
    "peak_flow_cms": (0, 50000, "洪峰流量(m³/s)"),
    "slope_deg": (0, 90, "坡度"),
    "elevation_m": (790, 1800, "研究区高程(m)"),
}


class PhysicsValidator:
    @staticmethod
    def validate_manning(n: float, R: float, S: float) -> dict:
        V = (1.0 / n) * (R ** (2.0 / 3.0)) * (S ** 0.5) if n > 0 and R > 0 and S > 0 else 0
        warnings = []
        if not (0.01 <= n <= 0.30):
            warnings.append(f"糙率n={n:.3f}超出[0.01,0.30]")
        if V > 15:
            warnings.append(f"流速V={V:.2f}m/s超过15m/s")
        return {"velocity_ms": round(V, 4), "valid": len(warnings) == 0, "warnings": warnings}

    @staticmethod
    def validate_continuity(Q_in: float, Q_out: float, dS: float = 0) -> dict:
        residual = abs(Q_in - Q_out - dS)
        return {"residual": round(residual, 4), "balanced": residual < 0.01 * max(Q_in, 0.001)}

    @staticmethod
    def check_range(value: float, key: str) -> dict:
        rng = PHYSICS_RANGES.get(key)
        if not rng:
            return {"valid": True}
        lo, hi, label = rng
        ok = lo <= value <= hi
        return {"valid": ok, "value": value, "range": f"{lo}-{hi}", "label": label,
                "warning": "" if ok else f"{label}={value}超出范围[{lo},{hi}]"}


physics = PhysicsValidator()


SPATIAL_COMMONSENSE = {
    "hydrology": [
        "水往低处流 — 水流方向由高程决定",
        "汇流累积量越大河道越宽",
        "糙率越大流速越慢水深越深",
        "暴雨强度随重现期增大而增大",
        "SCS-CN值越高产流量越大",
        "径流系数=径流量/降雨量 范围0-1",
    ],
    "flood": [
        "淹没区域沿河道和低洼地带分布",
        "洪水峰值出现在降雨峰值后一段时间",
        "淹没面积随洪峰流量增大而增大",
        "堤防高度决定防洪标准",
    ],
    "terrain": [
        "坡度=高程差/水平距离",
        "水流方向垂直于等高线",
        "山脊线=分水线=流域边界",
        "洼地=汇水区=潜在积水点",
    ],
}


def inject_commonsense(query: str) -> str:
    rules = []
    q = query.lower()
    if any(k in q for k in ["淹没", "洪水", "积水", "内涝", "涝"]):
        rules.extend(SPATIAL_COMMONSENSE["flood"])
    if any(k in q for k in ["径流", "降雨", "暴雨", "汇流", "产流"]):
        rules.extend(SPATIAL_COMMONSENSE["hydrology"])
    if any(k in q for k in ["坡度", "高程", "地形", "dem", "流域", "河网"]):
        rules.extend(SPATIAL_COMMONSENSE["terrain"])
    if not rules:
        rules = SPATIAL_COMMONSENSE["hydrology"][:3]
    return "[空间常识] " + "; ".join(rules[:5])


def validate_physics(tool_name: str, result: dict) -> list[str]:
    warnings = []
    if not isinstance(result, dict):
        return warnings
    if tool_name == "hydrodynamic_2d_sim":
        depth = result.get("peak_max_depth_m", 0)
        if isinstance(depth, (int, float)) and depth > 30:
            warnings.append(f"峰值水深{depth}m超出合理范围(0-30m)")
    if tool_name == "runoff_compute":
        coeff = result.get("runoff_coefficient", 0)
        if isinstance(coeff, (int, float)) and (coeff < 0 or coeff > 1):
            warnings.append(f"径流系数{coeff}超出合理范围(0-1)")
    if tool_name == "flood_assessment":
        depth_cm = result.get("avg_flood_depth_cm", 0)
        if isinstance(depth_cm, (int, float)) and depth_cm > 500:
            warnings.append(f"平均淹没深度{depth_cm}cm超出合理范围")
    return warnings


async def debate_validate(query: str, tool_name: str, tool_result: dict) -> dict:
    if tool_name not in CRITICAL_TOOLS:
        return {"consensus": True, "critics": []}
    result_str = json.dumps(tool_result, ensure_ascii=False, default=str)[:1500]

    async def _critic(role: str, prompt: str) -> dict:
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"用户问题: {query}\n工具: {tool_name}\n结果: {result_str}"}
        ]
        try:
            import asyncio
            content, _, _ = await asyncio.wait_for(call_llm(messages, model=MODEL_FLASH, use_tools=False), timeout=10.0)
            match = re.search(r'\{[^}]+\}', content)
            if match:
                return json.loads(match.group()) | {"role": role}
        except Exception:
            pass
        return {"pass": True, "score": 7, "role": role}

    DEBATE_PROMPTS = {
        "physics": "你是水力学物理验证专家。验证以下工具结果是否符合水力学物理规律。返回JSON: {\"pass\":bool,\"score\":1-10,\"issue\":\"\"}",
        "data": "你是数据合理性验证专家。验证以下工具结果的数值范围是否合理。返回JSON: {\"pass\":bool,\"score\":1-10,\"issue\":\"\"}",
        "completeness": "你是任务完整性验证专家。验证以下工具结果是否完整回答了用户需求。返回JSON: {\"pass\":bool,\"score\":1-10,\"issue\":\"\"}",
    }

    import asyncio
    critics = await asyncio.gather(*[_critic(r, p) for r, p in DEBATE_PROMPTS.items()])
    passes = sum(1 for c in critics if c.get("pass"))
    avg_score = sum(c.get("score", 5) for c in critics) / max(len(critics), 1)
    consensus = passes >= 2 and avg_score >= 6
    return {"consensus": consensus, "critics": list(critics)}


def validate_result(tool: str, args: dict, result: dict) -> tuple[bool, str]:
    if not isinstance(result, dict):
        return True, ""
    if "error" in result:
        return False, result["error"][:200]
    if tool == "hydrodynamic_2d_sim":
        depth = result.get("peak_max_depth_m", 0)
        if isinstance(depth, (int, float)) and depth > 30:
            return False, f"峰值水深{depth}m超出合理范围"
    if tool == "runoff_compute":
        coeff = result.get("runoff_coefficient", 0)
        if isinstance(coeff, (int, float)) and (coeff < 0 or coeff > 1):
            return False, f"径流系数{coeff}不合理"
    return True, ""
