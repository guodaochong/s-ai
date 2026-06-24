"""Intelligent report generator — transforms analysis results into
professional water-resources assessment reports.

GLM-4 AIR analyses the accumulated tool results / disaster assessments
/ video data and generates a structured report (summary, methodology,
findings, recommendations).  The text is injected into a self-contained
HTML template that can be previewed in-browser or printed to PDF.

Author: jumpingbirds <guodaochong@gmail.com>
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import structlog

from app.config import MODEL_AIR, logger
from app.llm import call_llm

__author__ = "jumpingbirds"
__email__ = "guodaochong@gmail.com"

logger = structlog.get_logger()


_REPORT_PROMPT = """你是水利空间智能体平台的首席分析师。根据以下分析数据，撰写一份专业的中文水利分析报告。

分析数据：
{data}

报告要求：
1. 摘要：100-200字概述分析目的、方法和核心发现
2. 分析方法：列出使用的数据源和分析工具
3. 主要发现：分点列出关键数据和发现（含具体数值）
4. 风险评估：基于数据给出风险等级和判断依据
5. 专业建议：3-5条可操作的建议措施

仅返回JSON：
{{"title":"报告标题","summary":"摘要","methodology":"方法描述","findings":["发现1","发现2"],"risk_level":"低/中/高/极高","risk_basis":"判断依据","recommendations":["建议1","建议2"]}}"""


def _format_tool_results(tools: list[dict]) -> str:
    lines: list[str] = []
    for t in tools:
        name = t.get("tool", "?")
        result = t.get("result", {})
        if isinstance(result, dict):
            key_vals = {k: v for k, v in result.items() if not k.startswith("_") and not isinstance(v, (list, dict))}
            preview = ", ".join(f"{k}={v}" for k, v in list(key_vals.items())[:5])
        else:
            preview = str(result)[:100]
        lines.append(f"- {name}: {preview}")
    return "\n".join(lines)


async def generate_report(
    tool_results: list[dict] | None = None,
    disaster_assessment: dict | None = None,
    video_analysis: dict | None = None,
    comparison: dict | None = None,
    user_query: str = "",
) -> str:
    data_parts: list[str] = []
    if user_query:
        data_parts.append(f"用户查询: {user_query}")
    if tool_results:
        data_parts.append(f"工具分析结果:\n{_format_tool_results(tool_results)}")
    if disaster_assessment:
        da = disaster_assessment
        data_parts.append(
            f"灾情评估: 类型={da.get('disaster_type','')}, 等级={da.get('severity','')}, "
            f"水深={da.get('water_depth_m','')}, 摘要={da.get('summary','')}"
        )
    if video_analysis:
        va = video_analysis
        data_parts.append(
            f"视频分析: 时长={va.get('duration',0)}s, 帧数={va.get('frame_count',0)}, "
            f"最大水面={va.get('max_water_ratio',0)}, 趋势={va.get('trend','')}"
        )
    if comparison and comparison.get("metrics"):
        metrics_str = "; ".join(
            f"{m['metric']}={', '.join(str(v['value']) for v in m['values'])}"
            for m in comparison["metrics"]
        )
        data_parts.append(f"多情景对比: {metrics_str}")

    if not data_parts:
        data_parts.append("无分析数据，请基于通用水利知识生成报告框架。")

    prompt = _REPORT_PROMPT.format(data="\n".join(data_parts))

    try:
        content, _, _ = await call_llm(
            [{"role": "user", "content": prompt}],
            model=MODEL_AIR,
            use_tools=False,
            max_tokens_override=2000,
        )
    except Exception as e:
        logger.error("[Report] LLM generation failed", error=str(e)[:200])
        content = '{"title":"分析报告","summary":"报告生成失败","methodology":"","findings":[],"risk_level":"未知","risk_basis":"","recommendations":[]}'

    import re
    match = re.search(r'\{.*\}', content, re.DOTALL)
    report_data: dict[str, Any] = {}
    if match:
        try:
            cleaned = match.group()
            if cleaned.startswith("```"):
                cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
                cleaned = re.sub(r'\s*```$', '', cleaned)
            report_data = json.loads(cleaned)
        except json.JSONDecodeError:
            pass

    return _render_html(report_data, tool_results, disaster_assessment, video_analysis, comparison)


def _risk_color(level: str) -> str:
    mapping = {"低": "#22c55e", "中": "#eab308", "高": "#f97316", "极高": "#ef4444"}
    for k, v in mapping.items():
        if k in level:
            return v
    return "#64748b"


def _render_html(
    report: dict[str, Any],
    tool_results: list[dict] | None,
    disaster: dict | None,
    video: dict | None,
    comparison: dict | None,
) -> str:
    title = report.get("title", "水利空间分析报告")
    now = datetime.now().strftime("%Y年%m月%d日 %H:%M")
    risk = report.get("risk_level", "未知")
    risk_color = _risk_color(risk)
    findings = report.get("findings", [])
    recommendations = report.get("recommendations", [])

    tool_table = ""
    if tool_results:
        rows = "".join(
            f"<tr><td>{t.get('tool','')}</td><td class='mono'>{_short_result(t.get('result',''))}</td></tr>"
            for t in tool_results[:15]
        )
        tool_table = f"""
        <h2>📎 工具调用明细</h2>
        <table class="data-table"><thead><tr><th>工具</th><th>关键结果</th></tr></thead><tbody>{rows}</tbody></table>"""

    disaster_section = ""
    if disaster:
        da = disaster
        buildings = da.get("affected_buildings", [])
        bld_tags = "".join(
            f'<span class="tag">{b.get("type","")} ×{b.get("count","")} <small>{b.get("status","")}</small></span>'
            for b in buildings
        ) if isinstance(buildings, list) else str(buildings)
        hazards = da.get("hazards", [])
        haz_tags = "".join(f'<span class="tag warn">{h}</span>' for h in hazards) if isinstance(hazards, list) else ""
        actions = da.get("recommended_actions", [])
        act_items = "".join(f"<li>{a}</li>" for a in actions) if isinstance(actions, list) else ""
        disaster_section = f"""
        <h2>🚨 灾情评估</h2>
        <div class="disaster-box">
            <div class="ds-row">
                <div class="ds-cell"><span class="ds-label">灾害类型</span><span class="ds-val">{da.get('disaster_type','—')}</span></div>
                <div class="ds-cell"><span class="ds-label">严重程度</span><span class="ds-val">{da.get('severity','—')}级</span></div>
                <div class="ds-cell"><span class="ds-label">估算水深</span><span class="ds-val">{da.get('water_depth_m','—')}m</span></div>
            </div>
            {'<div class="ds-tags">'+bld_tags+'</div>' if bld_tags else ''}
            {'<div class="ds-tags">'+haz_tags+'</div>' if haz_tags else ''}
            {'<ol class="ds-actions">'+act_items+'</ol>' if act_items else ''}
        </div>"""

    video_section = ""
    if video:
        va = video
        video_section = f"""
        <h2>📹 视频分析</h2>
        <div class="video-box">
            <div class="ds-row">
                <div class="ds-cell"><span class="ds-label">视频时长</span><span class="ds-val">{va.get('duration',0)}s</span></div>
                <div class="ds-cell"><span class="ds-label">分析帧数</span><span class="ds-val">{va.get('frame_count',0)}</span></div>
                <div class="ds-cell"><span class="ds-label">最大水面占比</span><span class="ds-val">{va.get('max_water_ratio',0)*100:.1f}%</span></div>
                <div class="ds-cell"><span class="ds-label">水体趋势</span><span class="ds-val">{va.get('trend','')}</span></div>
            </div>
        </div>"""

    comparison_section = ""
    if comparison and comparison.get("metrics"):
        header_cells = "".join(
            f"<th>{v['label']}</th>" for v in comparison["metrics"][0]["values"]
        ) if comparison["metrics"] else ""
        body_rows = ""
        for m in comparison["metrics"]:
            cells = "".join(f"<td>{_fmt_val(v['value'])}</td>" for v in m["values"])
            body_rows += f"<tr><td class='metric-name'>{m['metric']}</td>{cells}</tr>"
        comparison_section = f"""
        <h2>📊 多情景对比</h2>
        <table class="data-table"><thead><tr><th>指标</th>{header_cells}</tr></thead><tbody>{body_rows}</tbody></table>"""

    findings_html = "".join(f"<li>{f}</li>" for f in findings) if findings else "<li>暂无发现</li>"
    recs_html = "".join(f"<li>{r}</li>" for r in recommendations) if recommendations else "<li>暂无建议</li>"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: "Microsoft YaHei", "PingFang SC", sans-serif; background: #f0f2f5; color: #1a1a2e; line-height: 1.8; padding: 40px 20px; }}
.report {{ max-width: 800px; margin: 0 auto; background: #fff; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 24px rgba(0,0,0,.08); }}
.cover {{ background: linear-gradient(135deg, #0c4a6e 0%, #0369a1 50%, #0284c7 100%); color: #fff; padding: 48px 40px; text-align: center; }}
.cover h1 {{ font-size: 28px; margin-bottom: 12px; letter-spacing: 2px; }}
.cover .meta {{ font-size: 14px; opacity: .8; margin-top: 16px; }}
.cover .risk-badge {{ display: inline-block; margin-top: 20px; padding: 8px 28px; border-radius: 24px; font-size: 18px; font-weight: 700; background: {risk_color}; color: #fff; box-shadow: 0 2px 12px rgba(0,0,0,.2); }}
.body {{ padding: 40px; }}
h2 {{ font-size: 18px; color: #0c4a6e; margin: 28px 0 14px; padding-bottom: 8px; border-bottom: 2px solid #e0f2fe; }}
.summary {{ background: #f0f9ff; border-left: 4px solid #0284c7; padding: 16px 20px; border-radius: 0 8px 8px 0; font-size: 14px; color: #475569; }}
.section-text {{ font-size: 14px; color: #334155; margin: 10px 0; }}
ol {{ padding-left: 20px; margin: 10px 0; }}
ol li {{ font-size: 14px; color: #334155; margin-bottom: 8px; }}
.data-table {{ width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 13px; }}
.data-table th {{ background: #0c4a6e; color: #fff; padding: 8px 12px; text-align: left; font-weight: 600; }}
.data-table td {{ padding: 7px 12px; border-bottom: 1px solid #e2e8f0; color: #475569; }}
.data-table tr:nth-child(even) td {{ background: #f8fafc; }}
.mono {{ font-family: "Consolas", monospace; font-size: 12px; }}
.metric-name {{ font-weight: 600; color: #1e293b; white-space: nowrap; }}
.disaster-box, .video-box {{ background: #fef2f2; border-radius: 10px; padding: 16px 20px; margin: 12px 0; }}
.video-box {{ background: #ecfeff; }}
.ds-row {{ display: flex; gap: 16px; margin-bottom: 12px; }}
.ds-cell {{ flex: 1; text-align: center; }}
.ds-label {{ display: block; font-size: 11px; color: #94a3b8; }}
.ds-val {{ display: block; font-size: 16px; font-weight: 700; color: #1e293b; }}
.ds-tags {{ display: flex; gap: 6px; flex-wrap: wrap; margin: 8px 0; }}
.tag {{ padding: 3px 10px; border-radius: 6px; font-size: 12px; background: #fff; border: 1px solid #fecaca; color: #475569; }}
.tag.warn {{ background: #fee2e2; border-color: #f87171; color: #b91c1c; }}
.tag small {{ color: #dc2626; }}
.ds-actions {{ padding-left: 20px; }}
.ds-actions li {{ font-size: 13px; color: #475569; margin-bottom: 4px; }}
.footer {{ padding: 24px 40px; background: #f8fafc; border-top: 1px solid #e2e8f0; text-align: center; font-size: 12px; color: #94a3b8; }}
@media print {{ body {{ padding: 0; background: #fff; }} .report {{ box-shadow: none; border-radius: 0; }} }}
</style>
</head>
<body>
<div class="report">
    <div class="cover">
        <h1>📊 {title}</h1>
        <div class="meta">S-AI · 水利空间智能体平台 | {now}</div>
        <div class="meta">Author: jumpingbirds &lt;guodaochong@gmail.com&gt;</div>
        <div class="risk-badge">风险等级: {risk}</div>
    </div>
    <div class="body">
        <h2>📋 摘要</h2>
        <div class="summary">{report.get("summary", "")}</div>

        <h2>🔬 分析方法</h2>
        <p class="section-text">{report.get("methodology", "基于多源空间数据和水文模型进行综合分析。")}</p>

        <h2>📈 主要发现</h2>
        <ol>{findings_html}</ol>

        <h2>⚠️ 风险评估</h2>
        <div class="summary" style="border-left-color: {risk_color};">
            <strong>风险等级: {risk}</strong><br>
            {report.get("risk_basis", "基于分析数据综合判断。")}
        </div>

        <h2>💡 专业建议</h2>
        <ol>{recs_html}</ol>

        {disaster_section}
        {video_section}
        {comparison_section}
        {tool_table}
    </div>
    <div class="footer">
        本报告由 S-AI 水利空间智能体平台自动生成 | GLM-4 AIR + {len(tool_results or [])} 个空间分析工具<br>
        © 2026 jumpingbirds &lt;guodaochong@gmail.com&gt; | 报告仅供参考，重大决策请结合实地勘查
    </div>
</div>
</body>
</html>"""


def _short_result(result: Any) -> str:
    if isinstance(result, dict):
        vals = {k: v for k, v in result.items() if not k.startswith("_") and not isinstance(v, (list, dict))}
        return ", ".join(f"{k}={v}" for k, v in list(vals.items())[:4])
    return str(result)[:80]


def _fmt_val(v: Any) -> str:
    if isinstance(v, (int, float)):
        if v > 10000:
            return f"{v/10000:.1f}万"
        return str(v)
    return str(v)
