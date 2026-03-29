# ============================================================
# SAGA - RAG 参数推断器（Parameter Inferrer）
# 第 5 批 / 共 10 批
# 用途：读取 RAG 行业规则文本，通过 LLM（或 Mock）推断出
#       用户可配置的参数列表（带默认值、范围、类型、描述）
#       前端 DynamicParams 组件根据此列表动态渲染控件
# Pipeline 阶段：配置阶段（用户选择场景后立即推断）
# ============================================================

import asyncio
import json
import re
from typing import Dict, Any, List, Optional

from config import LLM_BACKEND
from utils.logger import get_logger, log_event

logger = get_logger("saga.rag.parameter_inferrer")


# ============================================================
# 各场景的 Mock 预设参数列表
# 这些参数是从 RAG 规则中人工提取的，LLM 模式下由 LLM 自动推断
# Mock 模式下直接返回这些预设，不依赖 LLM
# ============================================================

_MOCK_PARAMS_FINANCE = [
    {
        "name": "initial_balance_median",
        "label": "Initial Balance Median ($)",
        "type": "number",
        "default": 10000,
        "min": 100,
        "max": 1000000,
        "step": 1000,
        "description": "Median initial account balance for all nodes",
    },
    {
        "name": "transaction_amount_median",
        "label": "Transaction Amount Median ($)",
        "type": "number",
        "default": 500,
        "min": 10,
        "max": 100000,
        "step": 100,
        "description": "Median transaction amount (log-normal distribution)",
    },
    {
        "name": "reporting_threshold",
        "label": "Reporting Threshold ($)",
        "type": "number",
        "default": 10000,
        "min": 1000,
        "max": 100000,
        "step": 1000,
        "description": "Regulatory reporting threshold (structuring detection reference)",
    },
    {
        "name": "suspicious_account_ratio",
        "label": "Suspicious Account Ratio",
        "type": "slider",
        "default": 0.02,
        "min": 0.0,
        "max": 0.2,
        "step": 0.01,
        "description": "Proportion of accounts flagged as potentially suspicious (1-3% typical)",
    },
    {
        "name": "burstiness",
        "label": "Temporal Burstiness",
        "type": "slider",
        "default": 0.3,
        "min": 0.0,
        "max": 1.0,
        "step": 0.05,
        "description": "Burstiness index: 0=uniform, 1=extremely concentrated",
    },
    {
        "name": "working_hours_weight",
        "label": "Working Hours Weight (%)",
        "type": "slider",
        "default": 70,
        "min": 30,
        "max": 95,
        "step": 5,
        "description": "Percentage of transactions occurring during business hours (9:00-18:00)",
    },
    {
        "name": "anomaly_rate_target",
        "label": "Target Anomaly Rate (%)",
        "type": "slider",
        "default": 5,
        "min": 1,
        "max": 30,
        "step": 1,
        "description": "Approximate target percentage of anomalous edges in final graph",
    },
    {
        "name": "max_daily_transactions",
        "label": "Max Daily Transactions per Node",
        "type": "number",
        "default": 30,
        "min": 5,
        "max": 500,
        "step": 5,
        "description": "Maximum normal daily transaction count per account (high frequency threshold)",
    },
    {
        "name": "cycle_length_range",
        "label": "AML Cycle Length",
        "type": "select",
        "default": "3-7",
        "options": ["3-5", "3-7", "5-10", "3-10"],
        "description": "Circular laundering cycle length range (number of hops)",
    },
]

_MOCK_PARAMS_NETWORK = [
    {
        "name": "normal_connections_per_hour",
        "label": "Normal Connections/Hour",
        "type": "number",
        "default": 50,
        "min": 5,
        "max": 1000,
        "step": 10,
        "description": "Average new connections per hour for normal hosts",
    },
    {
        "name": "attack_ratio",
        "label": "Attack Traffic Ratio (%)",
        "type": "slider",
        "default": 10,
        "min": 1,
        "max": 50,
        "step": 1,
        "description": "Proportion of attack traffic in total traffic",
    },
    {
        "name": "burstiness",
        "label": "Temporal Burstiness",
        "type": "slider",
        "default": 0.4,
        "min": 0.0,
        "max": 1.0,
        "step": 0.05,
        "description": "Burstiness index for traffic temporal distribution",
    },
    {
        "name": "ddos_intensity",
        "label": "DDoS Attack Intensity",
        "type": "select",
        "default": "medium",
        "options": ["low", "medium", "high", "extreme"],
        "description": "DDoS attack intensity level (affects peak connection rate)",
    },
    {
        "name": "scan_port_range",
        "label": "Port Scan Range",
        "type": "select",
        "default": "common",
        "options": ["common", "extended", "full"],
        "description": "Port scan target range: common(1-1024), extended(1-10000), full(1-65535)",
    },
    {
        "name": "botnet_heartbeat_interval",
        "label": "Botnet Heartbeat (sec)",
        "type": "number",
        "default": 60,
        "min": 10,
        "max": 3600,
        "step": 10,
        "description": "C&C heartbeat interval in seconds",
    },
]

_MOCK_PARAMS_CYBER = [
    {
        "name": "attack_phases",
        "label": "ATT&CK Phases to Include",
        "type": "select",
        "default": "full_chain",
        "options": ["reconnaissance_only", "initial_access_to_lateral", "full_chain", "exfil_and_impact"],
        "description": "Which phases of the ATT&CK kill chain to simulate",
    },
    {
        "name": "lateral_movement_speed",
        "label": "Lateral Movement Speed",
        "type": "select",
        "default": "slow",
        "options": ["slow", "medium", "fast"],
        "description": "How quickly the attacker moves laterally (slow=days, fast=hours)",
    },
    {
        "name": "burstiness",
        "label": "Temporal Burstiness",
        "type": "slider",
        "default": 0.3,
        "min": 0.0,
        "max": 1.0,
        "step": 0.05,
        "description": "Burstiness of attack events",
    },
    {
        "name": "c2_beacon_interval",
        "label": "C&C Beacon Interval (sec)",
        "type": "number",
        "default": 300,
        "min": 30,
        "max": 86400,
        "step": 30,
        "description": "C&C communication heartbeat interval in seconds",
    },
    {
        "name": "compromised_host_ratio",
        "label": "Compromised Host Ratio",
        "type": "slider",
        "default": 0.05,
        "min": 0.01,
        "max": 0.3,
        "step": 0.01,
        "description": "Proportion of hosts that get compromised during the attack",
    },
    {
        "name": "exfil_size_mb",
        "label": "Exfiltration Size (MB)",
        "type": "number",
        "default": 500,
        "min": 10,
        "max": 10000,
        "step": 50,
        "description": "Total data exfiltrated in MB",
    },
]

_MOCK_PARAMS_TRAFFIC = [
    {
        "name": "road_capacity_vph",
        "label": "Road Capacity (veh/hour/lane)",
        "type": "number",
        "default": 1800,
        "min": 500,
        "max": 3000,
        "step": 100,
        "description": "Theoretical single-lane capacity in vehicles per hour",
    },
    {
        "name": "burstiness",
        "label": "Temporal Burstiness",
        "type": "slider",
        "default": 0.5,
        "min": 0.0,
        "max": 1.0,
        "step": 0.05,
        "description": "Burstiness of traffic flow (rush-hour peaking)",
    },
    {
        "name": "truck_ratio",
        "label": "Truck Ratio (%)",
        "type": "slider",
        "default": 10,
        "min": 0,
        "max": 30,
        "step": 1,
        "description": "Proportion of trucks in traffic mix",
    },
    {
        "name": "accident_probability",
        "label": "Accident Probability per Block",
        "type": "slider",
        "default": 0.02,
        "min": 0.0,
        "max": 0.2,
        "step": 0.005,
        "description": "Probability of an accident occurring in each time block",
    },
    {
        "name": "peak_saturation",
        "label": "Peak Saturation (%)",
        "type": "slider",
        "default": 90,
        "min": 50,
        "max": 120,
        "step": 5,
        "description": "Rush-hour flow as percentage of road capacity (>100% = over-saturated)",
    },
    {
        "name": "weather_condition",
        "label": "Weather Condition",
        "type": "select",
        "default": "clear",
        "options": ["clear", "rain", "heavy_rain", "snow", "fog"],
        "description": "Weather condition affecting speed and capacity",
    },
]

_MOCK_PARAMS_CUSTOM = [
    {
        "name": "burstiness",
        "label": "Temporal Burstiness",
        "type": "slider",
        "default": 0.3,
        "min": 0.0,
        "max": 1.0,
        "step": 0.05,
        "description": "Burstiness index for event temporal distribution",
    },
    {
        "name": "anomaly_rate_target",
        "label": "Target Anomaly Rate (%)",
        "type": "slider",
        "default": 5,
        "min": 1,
        "max": 30,
        "step": 1,
        "description": "Approximate target percentage of anomalous edges",
    },
]

# 场景 → Mock 参数映射
_MOCK_PARAMS_MAP = {
    "finance_aml": _MOCK_PARAMS_FINANCE,
    "network_ids": _MOCK_PARAMS_NETWORK,
    "cyber_apt": _MOCK_PARAMS_CYBER,
    "traffic": _MOCK_PARAMS_TRAFFIC,
    "custom": _MOCK_PARAMS_CUSTOM,
}


# ============================================================
# 推断函数（公开接口）
# ============================================================

def infer_parameters(rules_text, scenario_id=None, use_mock=None):
    # type: (str, Optional[str], Optional[bool]) -> List[Dict[str, Any]]
    """
    从 RAG 规则文本推断可配置参数列表

    输入：
      rules_text: RAG 规则文本（完整或摘要级）
      scenario_id: 场景 ID（Mock 模式下直接查表用）
      use_mock: 是否使用 Mock 模式（None 则根据 LLM_BACKEND 判断）
    输出：
      参数列表，每个参数是一个字典：
      {
        "name": str,          # 参数内部名（用作 JSON key）
        "label": str,         # 显示名（前端展示用）
        "type": str,          # 控件类型 "number" / "slider" / "select" / "text"
        "default": any,       # 默认值
        "min": number,        # 最小值（number/slider 类型用）
        "max": number,        # 最大值
        "step": number,       # 步进
        "options": list,      # 选项列表（select 类型用）
        "description": str,   # 参数说明
      }
    调用时机：用户选择场景后，前端发送 infer_parameters 请求
    """
    if use_mock is None:
        use_mock = (LLM_BACKEND.lower() == "mock")

    if use_mock:
        return _infer_mock(rules_text, scenario_id)
    else:
        # LLM 模式：构建 Prompt 让 LLM 分析规则文本并输出参数 JSON
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # 已在事件循环中
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(
                    asyncio.run,
                    _infer_llm(rules_text, scenario_id)
                ).result()
        else:
            return asyncio.run(_infer_llm(rules_text, scenario_id))


def _infer_mock(rules_text, scenario_id):
    # type: (str, Optional[str]) -> List[Dict[str, Any]]
    """
    Mock 模式：直接返回预设参数列表

    如果有 scenario_id 就查表，否则根据 rules_text 内容猜测场景
    """
    if scenario_id and scenario_id in _MOCK_PARAMS_MAP:
        params = _MOCK_PARAMS_MAP[scenario_id]
        log_event(0, "params_inferred",
                  "Mock 模式推断参数: {s} 场景, {n} 个参数".format(
                      s=scenario_id, n=len(params)))
        # 返回深拷贝避免外部修改影响预设
        import copy
        return copy.deepcopy(params)

    # 无 scenario_id：根据关键词猜测
    text_lower = rules_text.lower()
    if "aml" in text_lower or "transaction" in text_lower or "money" in text_lower:
        return _infer_mock(rules_text, "finance_aml")
    elif "ddos" in text_lower or "port scan" in text_lower or "network" in text_lower:
        return _infer_mock(rules_text, "network_ids")
    elif "att&ck" in text_lower or "lateral" in text_lower or "apt" in text_lower:
        return _infer_mock(rules_text, "cyber_apt")
    elif "traffic" in text_lower or "vehicle" in text_lower or "intersection" in text_lower:
        return _infer_mock(rules_text, "traffic")
    else:
        return _infer_mock(rules_text, "custom")


async def _infer_llm(rules_text, scenario_id):
    # type: (str, Optional[str]) -> List[Dict[str, Any]]
    """
    LLM 模式：让 LLM 分析规则文本并输出参数 JSON

    如果 LLM 推断失败，回退到 Mock 预设
    """
    from core.agent import LLMCaller

    prompt = _build_inference_prompt(rules_text)
    system_prompt = (
        "You are a parameter extraction system. Analyze domain rules and output "
        "a JSON array of configurable parameters. Respond ONLY with valid JSON, "
        "no markdown, no explanation."
    )

    caller = LLMCaller()
    response = await caller.call(prompt, system_prompt)

    if not response:
        logger.warning("LLM 参数推断无响应，回退到 Mock")
        return _infer_mock(rules_text, scenario_id)

    # 解析 JSON
    params = _parse_inference_response(response)
    if not params:
        logger.warning("LLM 参数推断解析失败，回退到 Mock")
        return _infer_mock(rules_text, scenario_id)

    log_event(0, "params_inferred",
              "LLM 模式推断参数: {n} 个".format(n=len(params)))
    return params


def _build_inference_prompt(rules_text):
    # type: (str) -> str
    """构建参数推断的 LLM Prompt"""
    return """Analyze the following domain rules and extract configurable parameters that a user might want to adjust when generating synthetic graph data.

=== Domain Rules ===
{rules}

=== Output Format ===
Return a JSON array where each element has:
- "name": parameter internal name (snake_case, English)
- "label": human-readable label (English)
- "type": one of "number", "slider", "select", "text"
- "default": sensible default value
- "min": minimum value (for number/slider)
- "max": maximum value (for number/slider)
- "step": step increment (for number/slider)
- "options": array of options (for select type only)
- "description": brief description of what this parameter controls

Extract 5-10 parameters that are most important for controlling the data generation.
Always include "burstiness" (temporal burstiness, slider 0-1) as one parameter.

Respond ONLY with the JSON array.""".format(rules=rules_text[:4000])


def _parse_inference_response(response_text):
    # type: (str) -> List[Dict[str, Any]]
    """解析 LLM 推断响应"""
    text = response_text.strip()
    # 去掉 markdown 包裹
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                return []
        else:
            return []

    if not isinstance(data, list):
        return []

    # 校验每个参数的必要字段
    valid = []
    for item in data:
        if not isinstance(item, dict):
            continue
        if "name" not in item or "type" not in item:
            continue
        # 补全缺失字段
        item.setdefault("label", item["name"])
        item.setdefault("default", 0)
        item.setdefault("description", "")
        if item["type"] in ("number", "slider"):
            item.setdefault("min", 0)
            item.setdefault("max", 100)
            item.setdefault("step", 1)
        if item["type"] == "select":
            item.setdefault("options", [])
        valid.append(item)

    return valid
