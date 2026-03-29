# ============================================================
# SAGA - RAG 行业规则模块初始化
# 第 5 批 / 共 10 批
# 用途：提供统一的规则访问接口，根据场景 ID 加载对应规则
#       四大预置行业：金融AML / 网络IDS / 软件安全APT / 交通
# Pipeline 阶段：Phase 3 Agent 读取规则注入 Prompt
# ============================================================

from typing import Dict, Any, Optional

from utils.logger import get_logger

logger = get_logger("saga.rag")


def get_rules_for_scenario(scenario_id, level="full"):
    # type: (str, str) -> str
    """
    根据场景 ID 加载对应行业的 RAG 规则文本

    输入：
      scenario_id: 场景标识，与 config.SUPPORTED_SCENARIOS 中的 id 对应
        "finance_aml" / "network_ids" / "cyber_apt" / "traffic" / "custom"
      level: 规则详细程度 "basic" 或 "full"
    输出：
      规则文本字符串（直接注入 Agent Prompt）
    调用时机：
      - 用户选择场景后，服务器加载规则
      - Phase 3 Agent 初始化时传入 rag_rules 参数

    注意：custom 场景返回空字符串，由用户自行提供规则文本
    """
    if scenario_id == "finance_aml":
        from rag.finance_rules import get_finance_rules
        return get_finance_rules(level)

    elif scenario_id == "network_ids":
        from rag.network_rules import get_network_rules
        return get_network_rules(level)

    elif scenario_id == "cyber_apt":
        from rag.cyber_rules import get_cyber_rules
        return get_cyber_rules(level)

    elif scenario_id == "traffic":
        from rag.traffic_rules import get_traffic_rules
        return get_traffic_rules(level)

    elif scenario_id == "custom":
        # 自定义场景：规则由用户在前端输入，这里返回空
        return ""

    else:
        logger.warning("未知场景 ID: %s，返回空规则", scenario_id)
        return ""


def get_rule_preview(scenario_id):
    # type: (str) -> Dict[str, Any]
    """
    获取场景规则的摘要预览（供前端 ScenarioSelector 显示）

    输入：scenario_id 场景标识
    输出：
      {
        "scenario_id": str,
        "rules_text": str,       # basic 级别的简短规则文本
        "rule_count": int,       # 规则条数（粗略估算）
        "full_length": int,      # full 级别的字符数
      }
    调用时机：用户在前端选择场景后，WebSocket 返回规则预览
    """
    basic_text = get_rules_for_scenario(scenario_id, level="basic")
    full_text = get_rules_for_scenario(scenario_id, level="full")

    # 粗略估算规则条数（按行中包含数字序号或 | 或 === 的行计数）
    rule_lines = [
        line for line in full_text.split("\n")
        if line.strip() and (
            line.strip()[0].isdigit() or
            line.strip().startswith("|") or
            line.strip().startswith("===")
        )
    ]

    return {
        "scenario_id": scenario_id,
        "rules_text": basic_text,
        "rule_count": len(rule_lines),
        "full_length": len(full_text),
    }


def get_scenario_hour_weights(scenario_id):
    # type: (str) -> Dict[int, int]
    """
    根据场景返回该行业的小时权重表（供 Agent Mock 模式时间采样用）

    不同行业有不同的时间模式：
    - 金融：工作时间 9-18 集中，凌晨极低
    - 网络：白天高峰，夜间 10-20%
    - 交通：双峰（早 7-9，晚 17-19）
    - 安全：正常行为白天，攻击任何时间

    输出：{hour: weight} 映射，hour 范围 0-23
    调用时机：SemanticAgent 初始化时读取

    TODO(扩展): 这些权重也可以作为 LLM 推断参数的一部分，让用户调整
    """
    if scenario_id == "finance_aml":
        return {
            0: 1, 1: 1, 2: 1, 3: 1, 4: 1, 5: 1,
            6: 3, 7: 5, 8: 8,
            9: 15, 10: 18, 11: 16,
            12: 10, 13: 12,
            14: 16, 15: 18, 16: 15, 17: 12,
            18: 8, 19: 6, 20: 4, 21: 3,
            22: 2, 23: 1,
        }
    elif scenario_id == "network_ids":
        return {
            0: 3, 1: 2, 2: 2, 3: 2, 4: 2, 5: 3,
            6: 5, 7: 8, 8: 12,
            9: 18, 10: 20, 11: 18,
            12: 14, 13: 16,
            14: 18, 15: 20, 16: 18, 17: 15,
            18: 10, 19: 8, 20: 6, 21: 5,
            22: 4, 23: 3,
        }
    elif scenario_id == "cyber_apt":
        # APT 攻击可能在任何时间，但正常行为还是白天多
        return {
            0: 5, 1: 5, 2: 6, 3: 6, 4: 5, 5: 4,
            6: 6, 7: 8, 8: 10,
            9: 14, 10: 15, 11: 14,
            12: 12, 13: 13,
            14: 14, 15: 15, 16: 14, 17: 12,
            18: 10, 19: 8, 20: 7, 21: 6,
            22: 6, 23: 5,
        }
    elif scenario_id == "traffic":
        # 双峰模式：早高峰 + 晚高峰
        return {
            0: 2, 1: 1, 2: 1, 3: 1, 4: 1, 5: 3,
            6: 8, 7: 20, 8: 25, 9: 15,
            10: 10, 11: 12,
            12: 14, 13: 12,
            14: 12, 15: 14, 16: 18,
            17: 25, 18: 22, 19: 15,
            20: 8, 21: 5, 22: 3, 23: 2,
        }
    else:
        # 默认：均匀
        return {h: 10 for h in range(24)}


__all__ = [
    "get_rules_for_scenario",
    "get_rule_preview",
    "get_scenario_hour_weights",
]
