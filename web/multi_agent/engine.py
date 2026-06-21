import logging
import json

logger = logging.getLogger(__name__)

AGENTS = {
    "hydrologist": {
        "name": "Hydrologist",
        "icon": "🌊",
        "color": "#00d4ff",
        "system": """You are a senior hydrologist specializing in flood hydrology and distributed hydrological modeling. You analyze flood scenarios from a water science perspective: rainfall-runoff processes, watershed response, peak discharge, flow routing, infiltration, and surface water dynamics.

Your expertise:
- SCS-CN curve number method and distributed runoff generation
- Time-area flow routing and unit hydrograph theory
- Flood frequency analysis and return period estimation
- Manning's equation and open channel hydraulics
- Soil moisture, antecedent conditions, and infiltration modeling

When analyzing, focus on:
1. Hydrological processes (rainfall -> infiltration -> runoff -> routing)
2. Peak discharge timing and magnitude
3. Watershed response characteristics
4. Soil and land use effects on runoff

Be concise, quantitative, and professional. Use specific numbers when available. Respond in Chinese.""",
    },
    "engineer": {
        "name": "Structural Engineer",
        "icon": "🏗️",
        "color": "#f59e0b",
        "system": """You are a senior water resources structural engineer specializing in dam safety, levee design, flood control infrastructure, and hydraulic structures. You assess flood impacts on infrastructure from an engineering perspective.

Your expertise:
- Dam and levee safety analysis, breach modeling
- Flood control structure design standards (return periods, freeboard)
- Bridge and culvert hydraulic capacity assessment
- Urban drainage infrastructure performance under extreme rainfall
- Infrastructure resilience and failure mode analysis

When analyzing, focus on:
1. Infrastructure safety margins and design standards
2. Potential failure modes and cascading risks
3. Engineering mitigation measures (levees, retention ponds, drainage upgrades)
4. Cost-benefit analysis of flood defense options

Be concise, practical, and engineering-focused. Respond in Chinese.""",
    },
    "commander": {
        "name": "Emergency Commander",
        "icon": "🚨",
        "color": "#ef4444",
        "system": """You are a senior emergency management commander specializing in flood disaster response, evacuation planning, and risk communication. You assess flood scenarios from a public safety and operational perspective.

Your expertise:
- Emergency evacuation route planning and population protection
- Risk communication and warning systems
- Resource allocation for emergency response (personnel, equipment, shelters)
- Critical infrastructure protection during floods
- Post-disaster damage assessment and recovery planning

When analyzing, focus on:
1. Population at risk and evacuation priorities
2. Critical infrastructure exposure (hospitals, schools, power stations)
3. Emergency response resource needs
4. Evacuation route planning and shelter capacity
5. Long-term recovery and resilience building

Be concise, action-oriented, and prioritize human safety. Respond in Chinese.""",
    },
}

CONSENSUS_PROMPT = """You are a crisis coordination AI that synthesizes multiple expert opinions into a unified action plan.

Three experts have analyzed a flood scenario:
1. Hydrologist: focused on water processes
2. Structural Engineer: focused on infrastructure safety
3. Emergency Commander: focused on public safety

Synthesize their views into a CONSENSUS REPORT with these sections:
1. 风险等级评估 (Risk Level Assessment) - consensus severity rating
2. 关键风险点 (Critical Risk Points) - agreed top 3 risks
3. 紧急措施 (Emergency Measures) - immediate actions needed
4. 工程建议 (Engineering Recommendations) - medium-term solutions
5. 分歧记录 (Dissenting Opinions) - any unresolved disagreements

Be concise and actionable. Respond in Chinese."""


async def run_multi_agent_debate(
    call_llm_fn,
    context: str,
    rounds: int = 2,
) -> dict:
    import asyncio
    agents_data = list(AGENTS.keys())
    all_rounds = []
    agent_contexts: dict[str, str] = {}

    async def call_agent(agent_id: str, prompt: str, rnd: int, rtype: str):
        agent = AGENTS[agent_id]
        messages = [
            {"role": "system", "content": agent["system"]},
            {"role": "user", "content": prompt},
        ]
        for attempt in range(3):
            try:
                content, reasoning, _ = await call_llm_fn(messages, use_tools=False)
                break
            except Exception as e:
                if "429" in str(e) and attempt < 2:
                    await asyncio.sleep(3 * (attempt + 1))
                else:
                    content = f"[API error: {str(e)[:50]}]"
                    reasoning = ""
                    break
        return {
            "round": rnd, "agent": agent_id, "name": agent["name"],
            "icon": agent["icon"], "color": agent["color"],
            "content": content, "reasoning": reasoning[:200] if reasoning else "",
            "type": rtype,
        }

    async def call_round(agent_tasks):
        results = []
        for i, task_fn in enumerate(agent_tasks):
            if i > 0:
                await asyncio.sleep(2)
            results.append(await task_fn)
        return results

    tasks = [
        call_agent(aid, f"场景: {context}\n\n请从你的专业角度分析，给出具体数据和建议。150字以内。", 1, "initial")
        for aid in agents_data
    ]
    results = await call_round(tasks)
    for r in results:
        agent_contexts[r["agent"]] = r["content"]
        all_rounds.append(r)
        logger.info(f"[debate] R1 {r['name']}: {r['content'][:60]}...")

    for round_num in range(2, rounds + 1):
        other_views = "\n\n".join([
            f"[{AGENTS[aid]['name']}]: {agent_contexts[aid]}"
            for aid in agents_data
        ])
        tasks = [
            call_agent(aid, f"场景: {context}\n\n其他专家观点:\n{other_views}\n\n请质疑/补充/认同。100字以内。", round_num, "debate")
            for aid in agents_data
        ]
        results = await call_round(tasks)
        for r in results:
            agent_contexts[r["agent"]] = r["content"]
            all_rounds.append(r)
            logger.info(f"[debate] R{round_num} {r['name']}: {r['content'][:60]}...")

    consensus_messages = [
        {"role": "system", "content": CONSENSUS_PROMPT},
        {"role": "user", "content": f"场景: {context}\n\n专家讨论:\n" + "\n\n".join([
            f"[{r['name']}](R{r['round']}): {r['content']}" for r in all_rounds
        ])},
    ]
    consensus_content, _, _ = await call_llm_fn(consensus_messages, use_tools=False)
    logger.info(f"[debate] Consensus: {consensus_content[:80]}...")

    return {
        "multi_agent_debate": True,
        "context": context,
        "rounds": rounds,
        "n_agents": len(agents_data),
        "debate_log": all_rounds,
        "consensus": consensus_content,
        "agents": [{"id": aid, "name": AGENTS[aid]["name"], "icon": AGENTS[aid]["icon"], "color": AGENTS[aid]["color"]} for aid in agents_data],
    }
