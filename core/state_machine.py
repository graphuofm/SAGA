# ============================================================
# SAGA - Phase 4: 全局状态机 / 对齐结算引擎（Graph State Machine）
# 第 3 批 / 共 10 批
# 用途：接收 Phase 3 产出的所有微观边，
#       按 micro_time 全局排序后逐条处理，
#       维护每个节点的实时状态（余额/风险/冻结），
#       根据业务规则检测冲突并转化为异常标签（Ground Truth）
# Pipeline 阶段：Phase 4（对齐结算 — 冲突→异常标签）
# ============================================================

import copy
from collections import Counter, defaultdict
from typing import Dict, Any, List, Optional, Tuple

import numpy as np

from config import (
    parse_micro_time_key, micro_time_to_sortable_int,
)
from utils.logger import get_logger, log_event, progress_tracker

logger = get_logger("saga.core.state_machine")


# ============================================================
# 节点状态数据结构
# ============================================================

def _new_node_state(node_id, initial_balance=10000):
    # type: (str, int) -> Dict[str, Any]
    """
    创建一个新的节点状态字典

    每个节点在 Phase 4 中持续维护以下状态：
    - balance: 当前余额（随交易实时变化）
    - risk_level: 风险等级 low → medium → high → frozen
    - status: 账户状态 active / frozen / suspended
    - transaction_count: 累计交易次数
    - anomaly_count: 累计异常次数
    - last_transaction_time: 最后一笔交易的 micro_time
    - daily_transaction_count: 当天交易次数（用于高频检测，按天重置）
    - daily_amount_total: 当天累计交易金额
    - current_day: 当前所处的天（用于跨天重置日内计数器）
    - counterparties: 该节点交易过的对手方集合
    """
    return {
        "node_id": node_id,
        "balance": initial_balance,
        "risk_level": "low",
        "status": "active",
        "transaction_count": 0,
        "anomaly_count": 0,
        "last_transaction_time": "",
        "daily_transaction_count": 0,
        "daily_amount_total": 0,
        "current_day": "",
        "counterparties": set(),
    }


# ============================================================
# 风险升级链定义
# ============================================================

# 风险等级升级阈值和路径
# low → medium → high → frozen
# CONFIG: 这些阈值可以由 RAG 规则覆盖
_RISK_ESCALATION = {
    "low": {
        "anomaly_threshold": 2,    # 累计 2 次异常后升级到 medium
        "next_level": "medium",
    },
    "medium": {
        "anomaly_threshold": 4,    # 累计 4 次异常后升级到 high
        "next_level": "high",
    },
    "high": {
        "anomaly_threshold": 6,    # 累计 6 次异常后冻结
        "next_level": "frozen",
    },
    "frozen": {
        "anomaly_threshold": 999,  # 已冻结，不再升级
        "next_level": "frozen",
    },
}


class GraphStateMachine:
    """
    Phase 4 全局状态机 / 对齐结算引擎

    职责：
    1. 全局时间排序：将所有微观边按 micro_time 排序（最关键的一步！）
    2. 逐条处理：按时间顺序逐条执行业务规则校验
    3. 状态维护：实时更新每个节点的余额、风险、冻结状态
    4. 冲突标记：余额不足→anomaly_overdraft，账户冻结→anomaly_blocked，等等
    5. 风险升级：异常累计触发 low→medium→high→frozen 升级链
    6. 蝴蝶效应：早期异常通过状态继承影响后续所有交易

    核心设计原则：
    - 时间排序保证因果关系严格成立
    - 跨时间块的节点状态完整继承（Day_1 冻结 → Day_2 仍然冻结）
    - 冲突"自然涌现"为异常标签，而非预设
    """

    def __init__(self, initial_balances=None):
        # type: (Optional[Dict[str, int]]) -> None
        """
        输入：
          initial_balances: 节点初始余额映射 { "N_0001": 35000, ... }
                           由 Phase 2 TaskDispatcher.get_initial_balances() 提供
                           如果为 None，新节点使用默认余额 10000
        """
        self._initial_balances = initial_balances or {}

        # --- 核心状态 ---
        # 所有节点的当前状态（Phase 4 运行期间持续更新）
        self.node_states = {}  # type: Dict[str, Dict[str, Any]]

        # Phase 4 结算后的所有边（最终产物）
        self.final_edges = []  # type: List[Dict[str, Any]]

        # 统计计数器
        self._stats = {
            "total_processed": 0,
            "normal_count": 0,
            "anomaly_count": 0,
            "blocked_count": 0,
            "corrected_count": 0,
            "total_amount_transferred": 0,
            "anomaly_breakdown": Counter(),
        }

    def reset(self, initial_balances=None):
        # type: (Optional[Dict[str, int]]) -> None
        """重置状态机"""
        if initial_balances is not None:
            self._initial_balances = initial_balances
        self.node_states.clear()
        self.final_edges.clear()
        self._stats = {
            "total_processed": 0,
            "normal_count": 0,
            "anomaly_count": 0,
            "blocked_count": 0,
            "corrected_count": 0,
            "total_amount_transferred": 0,
            "anomaly_breakdown": Counter(),
        }

    # ============================================================
    # 核心方法：全局排序 + 逐条处理
    # ============================================================

    def process_all_edges(self, micro_edges):
        # type: (List[Dict[str, Any]]) -> List[Dict[str, Any]]
        """
        Phase 4: 一次性批量修正（不删边，改金额）

        流程：
        1. 全局按 micro_time 排序
        2. 初始化节点状态
        3. 逐条扫描：
           - 余额不足 → 修正金额为可用余额的 50-80%
           - 异常边（Agent 标记）→ 保留标签不动
           - 正常边 → 正常扣减余额
        4. 所有边都保留，边数 = 输入边数，精确不变
        """
        log_event(4, "settlement_start",
                  "对齐修正开始: {n} 条微观边".format(n=len(micro_edges)))

        sorted_edges = self._sort_edges_by_time(micro_edges)
        self._init_node_states(sorted_edges)
        progress_tracker.set_phase(4, total_expected=len(sorted_edges))

        import random as _rand

        for idx, edge in enumerate(sorted_edges):
            source = edge.get("source", "")
            target = edge.get("target", "")
            amount = edge.get("amount", 0)
            micro_time = edge.get("micro_time", "")
            properties = edge.get("properties", {})
            is_anomaly = edge.get("is_anomaly", False)
            anomaly_type = edge.get("anomaly_type", "")

            self._ensure_node_state(source)
            self._ensure_node_state(target)
            src_state = self.node_states[source]
            tgt_state = self.node_states[target]
            self._check_day_rollover(src_state, micro_time)
            self._check_day_rollover(tgt_state, micro_time)

            # --- 修正金额（不删边！）---
            if amount > 0 and src_state.get("balance", 0) < amount:
                available = max(1, src_state.get("balance", 0))
                amount = max(1, int(available * _rand.uniform(0.5, 0.8)))
                edge["amount"] = amount
                self._stats["corrected_count"] += 1

            # --- 确定标签 ---
            if is_anomaly:
                tag = anomaly_type if anomaly_type else "anomaly_agent"
                anomaly_reason = properties.get("anomaly_reason", "Agent-generated anomaly")
            else:
                tag = "normal"
                anomaly_reason = ""

            # --- 更新余额 ---
            src_state["balance"] -= amount
            tgt_state["balance"] += amount
            self._stats["total_amount_transferred"] += amount

            # 更新计数器
            src_state["transaction_count"] += 1
            tgt_state["transaction_count"] += 1
            src_state["daily_transaction_count"] += 1
            src_state["daily_amount_total"] += amount
            src_state["last_transaction_time"] = micro_time
            tgt_state["last_transaction_time"] = micro_time
            src_state["counterparties"].add(target)
            tgt_state["counterparties"].add(source)

            if tag != "normal":
                src_state["anomaly_count"] += 1
                self._stats["anomaly_count"] += 1
                self._stats["anomaly_breakdown"][tag] += 1
                self._escalate_risk(src_state)
            else:
                self._stats["normal_count"] += 1

            self._stats["total_processed"] += 1

            final_edge = {
                "time": micro_time,
                "u": source,
                "v": target,
                "amt": amount,
                "tag": tag,
                "anomaly_reason": anomaly_reason,
                "status": "success",
                "properties": properties,
            }
            self.final_edges.append(final_edge)
            progress_tracker.update(edge_index=idx + 1)

        log_event(4, "settlement_complete",
                  "对齐修正完成: {total} 条, 正常 {n}, 异常 {a}, 修正 {c}".format(
                      total=self._stats["total_processed"],
                      n=self._stats["normal_count"],
                      a=self._stats["anomaly_count"],
                      c=self._stats["corrected_count"]),
                  {"stats": self.get_statistics()})

        return self.final_edges


    def _check_conflict(self, source, target, amount, src_state, tgt_state):
        # type: (str, str, int, Dict, Dict) -> Tuple[bool, str]
        """
        snapshot 握手检测：检查这条边是否与当前全局状态矛盾

        矛盾条件（返回 True → 删除这条边）：
        1. 发送方余额不足（Agent 不知真实余额导致的冲突）
        2. 发送方或接收方已冻结（之前 snapshot 冻结了但后面 Agent 不知道）
        3. 节点不存在（脏数据）

        注意：这不是异常检测！矛盾边是逻辑错误，直接删除。
        """
        # 冻结账户的边 → 矛盾（Agent 生成时不知道已被冻结）
        if src_state.get("status") == "frozen":
            return (True, "Source {s} is frozen".format(s=source))
        if tgt_state.get("status") == "frozen":
            return (True, "Target {t} is frozen".format(t=target))

        # 余额不足 → 矛盾（Agent 用 UNKNOWN 余额生成导致超支）
        if amount > 0 and src_state.get("balance", 0) < amount:
            return (True, "Insufficient: have {b}, need {a}".format(
                b=src_state.get("balance", 0), a=amount))

        return (False, "")

    def process_single_edge(self, edge):
        # type: (Dict[str, Any]) -> Dict[str, Any]
        """
        处理单条微观边：执行业务规则校验并返回结算结果

        输入：
          edge: 微观边字典
            {
              micro_time: "Day_5_14:23",
              source: "N_0001",
              target: "N_0002",
              amount: 5000,
              properties: { transaction_type, risk_score, ip, device, ... }
            }
        输出：
          FinalEdge 字典
            {
              time: "Day_5_14:23",
              u: "N_0001",
              v: "N_0002",
              amt: 5000,
              tag: "normal" | "anomaly_xxx",
              anomaly_reason: "" | "原因描述",
              status: "success" | "failed" | "blocked",
              properties: { ... }
            }
        调用时机：process_all_edges 内部循环每条边调用一次
        """
        source = edge.get("source", "")
        target = edge.get("target", "")
        amount = edge.get("amount", 0)
        micro_time = edge.get("micro_time", "")
        properties = edge.get("properties", {})

        # 确保节点状态已初始化
        self._ensure_node_state(source)
        self._ensure_node_state(target)

        src_state = self.node_states[source]
        tgt_state = self.node_states[target]

        # --- 跨天重置日内计数器 ---
        self._check_day_rollover(src_state, micro_time)
        self._check_day_rollover(tgt_state, micro_time)

        # --- 执行业务规则检查 ---
        tag, anomaly_reason, status = self._check_business_rules(
            source, target, amount, micro_time, properties,
            src_state, tgt_state
        )

        # --- 更新节点状态 ---
        if status == "success":
            # 正常交易：扣减发送方余额，增加接收方余额
            src_state["balance"] -= amount
            tgt_state["balance"] += amount
            self._stats["total_amount_transferred"] += amount
        # failed / blocked 状态不改变余额

        # 更新通用计数器
        src_state["transaction_count"] += 1
        tgt_state["transaction_count"] += 1
        src_state["daily_transaction_count"] += 1
        src_state["daily_amount_total"] += amount
        src_state["last_transaction_time"] = micro_time
        tgt_state["last_transaction_time"] = micro_time

        # 记录对手方
        src_state["counterparties"].add(target)
        tgt_state["counterparties"].add(source)

        # 更新异常相关
        if tag != "normal":
            src_state["anomaly_count"] += 1
            self._stats["anomaly_count"] += 1
            self._stats["anomaly_breakdown"][tag] += 1

            # --- 风险升级链 ---
            self._escalate_risk(src_state)

            if status == "blocked":
                self._stats["blocked_count"] += 1

            log_event(4, "anomaly_detected",
                      "{t}: {s}→{tg} ${a} [{tag}] {reason}".format(
                          t=micro_time, s=source, tg=target,
                          a=amount, tag=tag, reason=anomaly_reason))
        else:
            self._stats["normal_count"] += 1

        self._stats["total_processed"] += 1

        # --- 组装 FinalEdge ---
        final_edge = {
            "time": micro_time,
            "u": source,
            "v": target,
            "amt": amount,
            "tag": tag,
            "anomaly_reason": anomaly_reason,
            "status": status,
            "properties": properties,
        }

        return final_edge

    def process_single_edge_with_progress(self, edge):
        # type: (Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any], Optional[Dict[str, Any]]]
        """
        处理单条边并返回进度信息和相关节点状态（供服务器逐条推送）

        输入：edge 微观边字典
        输出：
          (final_edge, node_states_snapshot, anomaly_info_or_none)
          - final_edge: 结算结果
          - node_states_snapshot: 相关两个节点的当前状态快照
          - anomaly_info: 如果是异常则返回异常信息，否则 None
        调用时机：server.py 在 Phase 4 循环中调用，
                  结果直接序列化为 WebSocket 消息推送给前端
        """
        final_edge = self.process_single_edge(edge)

        source = final_edge["u"]
        target = final_edge["v"]

        # 生成节点状态快照（不含 set 类型，方便 JSON 序列化）
        node_states_snapshot = {
            source: self._serialize_node_state(self.node_states.get(source, {})),
            target: self._serialize_node_state(self.node_states.get(target, {})),
        }

        # 异常信息
        anomaly_info = None
        if final_edge["tag"] != "normal":
            anomaly_info = {
                "time": final_edge["time"],
                "u": final_edge["u"],
                "v": final_edge["v"],
                "amt": final_edge["amt"],
                "tag": final_edge["tag"],
                "anomaly_reason": final_edge["anomaly_reason"],
                "properties": final_edge["properties"],
            }

        return (final_edge, node_states_snapshot, anomaly_info)

    # ============================================================
    # 业务规则检查（5 种异常标签）
    # ============================================================

    def _check_business_rules(self, source, target, amount, micro_time,
                               properties, src_state, tgt_state):
        # type: (str, str, int, str, Dict, Dict, Dict) -> Tuple[str, str, str]
        """
        执行所有业务规则检查，返回 (tag, anomaly_reason, status)

        规则按优先级从高到低：
        1. 账户冻结检查（最高优先级，直接拦截）
        2. 余额不足检查（overdraft）
        3. 高风险大额拦截
        4. 高频交易检测
        5. 大额交易检测

        输出 tag 取值：
          "normal"                   — 正常交易
          "anomaly_blocked"          — 冻结账户尝试交易
          "anomaly_overdraft"        — 余额不足
          "anomaly_high_risk_blocked"— 高风险+大额被拦截
          "anomaly_high_frequency"   — 高频交易（放行但标记）
          "anomaly_large_amount"     — 异常大额（放行但标记）

        输出 status 取值：
          "success"  — 交易成功（余额变化）
          "failed"   — 交易失败（余额不变，如 overdraft）
          "blocked"  — 交易被拦截（余额不变，如冻结）

        TODO(扩展): 第5批可以根据 RAG 场景动态加载额外规则
        """
        # --- 规则 1: 账户冻结检查 ---
        # 冻结账户的任何交易都被拦截
        if src_state.get("status") == "frozen":
            return (
                "anomaly_blocked",
                "Source account {s} is frozen".format(s=source),
                "blocked"
            )
        if tgt_state.get("status") == "frozen":
            return (
                "anomaly_blocked",
                "Target account {t} is frozen".format(t=target),
                "blocked"
            )

        # --- 规则 2: 余额不足检查（overdraft）---
        # 发送方余额不足以支付交易金额
        if amount > 0 and src_state.get("balance", 0) < amount:
            return (
                "anomaly_overdraft",
                "Insufficient balance: have {b}, need {a}".format(
                    b=src_state.get("balance", 0), a=amount),
                "failed"
            )

        # --- 规则 3: 高风险 + 大额 → 拦截 ---
        # 风险等级为 high 且交易金额超过阈值时直接拦截
        # CONFIG: 阈值可由 RAG 规则定义
        high_risk_threshold = 5000  # TODO(扩展): 从 RAG 配置读取
        if src_state.get("risk_level") == "high" and amount > high_risk_threshold:
            return (
                "anomaly_high_risk_blocked",
                "High-risk account {s} attempting large transfer ${a}".format(
                    s=source, a=amount),
                "blocked"
            )

        # --- 规则 4: 高频交易检测 ---
        # 当天交易次数超过阈值则标记（但放行）
        # CONFIG: 阈值可调
        high_freq_threshold = 20  # TODO(扩展): 从 RAG 配置读取
        if src_state.get("daily_transaction_count", 0) > high_freq_threshold:
            return (
                "anomaly_high_frequency",
                "High frequency: {n} transactions today from {s}".format(
                    n=src_state["daily_transaction_count"], s=source),
                "success"  # 放行但标记
            )

        # --- 规则 5: 异常大额检测 ---
        # 单笔金额超过 large_amount_threshold 标记（但放行）
        # CONFIG: 阈值可调
        large_amount_threshold = 10000  # TODO(扩展): 从 RAG 配置读取
        if amount > large_amount_threshold:
            return (
                "anomaly_large_amount",
                "Large transaction: ${a} from {s} to {t}".format(
                    a=amount, s=source, t=target),
                "success"  # 放行但标记
            )

        # --- 所有规则通过 → 正常交易 ---
        return ("normal", "", "success")

    # ============================================================
    # 风险升级链
    # ============================================================

    def _escalate_risk(self, node_state):
        # type: (Dict[str, Any]) -> None
        """
        根据累计异常次数执行风险升级

        升级链：low → medium → high → frozen
        每个等级有对应的异常次数阈值，达到后自动升级

        蝴蝶效应：一旦升级为 high，后续大额交易被拦截
                  一旦冻结，该节点所有后续交易都被拦截
                  这种级联效应会随时间传播到与之关联的节点
        """
        current_level = node_state.get("risk_level", "low")
        anomaly_count = node_state.get("anomaly_count", 0)

        escalation = _RISK_ESCALATION.get(current_level, {})
        threshold = escalation.get("anomaly_threshold", 999)
        next_level = escalation.get("next_level", current_level)

        if anomaly_count >= threshold and next_level != current_level:
            old_level = current_level
            node_state["risk_level"] = next_level

            # 冻结时更新 status
            if next_level == "frozen":
                node_state["status"] = "frozen"

            log_event(4, "risk_escalation",
                      "{nid}: {old} → {new} (anomaly_count={ac})".format(
                          nid=node_state["node_id"],
                          old=old_level, new=next_level,
                          ac=anomaly_count))

    # ============================================================
    # 时间排序（Phase 4 最关键的一步）
    # ============================================================

    def _sort_edges_by_time(self, micro_edges):
        # type: (List[Dict[str, Any]]) -> List[Dict[str, Any]]
        """
        将所有微观边按 micro_time 全局排序

        这是 SAGA 中最关键的步骤！
        时序图的正确性完全依赖于排序的正确性。
        如果排序错了 → 余额校验错了 → 异常标签不对 → Ground Truth 不准

        排序策略（根据边数量自动选择）：
        - < 500 万边：Python sorted() + parse_micro_time_key（元组比较）
        - ≥ 500 万边：numpy argsort + micro_time_to_sortable_int（整数比较）
        """
        n = len(micro_edges)
        if n == 0:
            return []

        log_event(4, "sort_start",
                  "全局时间排序: {n} 条微观边".format(n=n))

        if n < 5000000:
            # PERF: 小规模直接内存排序，使用元组 key
            sorted_edges = sorted(
                micro_edges,
                key=lambda e: parse_micro_time_key(e.get("micro_time", ""))
            )
        else:
            # PERF: 大规模用 numpy C 底层排序，整数 key
            logger.info("大规模排序模式: 使用 numpy argsort")
            time_keys = np.array(
                [micro_time_to_sortable_int(e.get("micro_time", ""))
                 for e in micro_edges],
                dtype=np.int64
            )
            sorted_indices = np.argsort(time_keys, kind="mergesort")  # 稳定排序
            sorted_edges = [micro_edges[i] for i in sorted_indices]

        # 验证排序正确性（Debug 级别日志）
        if len(sorted_edges) >= 2:
            first_time = sorted_edges[0].get("micro_time", "")
            last_time = sorted_edges[-1].get("micro_time", "")
            logger.debug("排序范围: %s → %s", first_time, last_time)

        log_event(4, "sort_complete",
                  "排序完成: {n} 条, {first} → {last}".format(
                      n=n,
                      first=sorted_edges[0].get("micro_time", "") if sorted_edges else "",
                      last=sorted_edges[-1].get("micro_time", "") if sorted_edges else ""))

        return sorted_edges

    # ============================================================
    # 节点状态管理
    # ============================================================

    def _init_node_states(self, sorted_edges):
        # type: (List[Dict[str, Any]]) -> None
        """
        从排序后的边中提取所有涉及的节点并初始化状态

        调用时机：process_all_edges 开始时
        """
        all_nodes = set()
        for edge in sorted_edges:
            all_nodes.add(edge.get("source", ""))
            all_nodes.add(edge.get("target", ""))
        all_nodes.discard("")

        for node_id in all_nodes:
            self._ensure_node_state(node_id)

        logger.info("初始化 %d 个节点状态", len(self.node_states))

    def _ensure_node_state(self, node_id):
        # type: (str) -> None
        """确保节点状态已初始化（惰性初始化）"""
        if node_id and node_id not in self.node_states:
            balance = self._initial_balances.get(node_id, 10000)
            self.node_states[node_id] = _new_node_state(node_id, balance)

    def _check_day_rollover(self, node_state, micro_time):
        # type: (Dict[str, Any], str) -> None
        """
        检查是否跨天，如果跨天则重置日内计数器

        从 micro_time 中提取天数标签（如 "Day_5"），
        与节点记录的 current_day 比较，不同则重置。

        为什么需要跨天重置？
        高频交易检测是"每天"维度的，Day_5 的交易次数不应累计 Day_4 的
        但余额、风险等级不重置（跨天继承！这是时序因果链的基础）
        """
        # 提取天标签（取 micro_time 的前两段）
        parts = micro_time.split("_")
        if len(parts) >= 2:
            day_label = "{p}_{d}".format(p=parts[0], d=parts[1])
        else:
            day_label = micro_time

        if node_state.get("current_day", "") != day_label:
            # 跨天：重置日内计数器
            node_state["current_day"] = day_label
            node_state["daily_transaction_count"] = 0
            node_state["daily_amount_total"] = 0
            # 注意：balance, risk_level, status, anomaly_count 不重置！
            # 这保证了跨时间块的状态继承

    # ============================================================
    # 查询接口
    # ============================================================

    def get_node_detail(self, node_id):
        # type: (str) -> Dict[str, Any]
        """
        获取单个节点的完整详情（供前端 NodeDetail 面板）

        输入：node_id 节点 ID
        输出：
          {
            "node_id": "N_0001",
            "current_state": { 完整节点状态 },
            "related_edges": [ 该节点关联的所有已结算边 ],
            "timeline": [ 按时间排序的事件列表 ]
          }
        调用时机：用户在图上点击节点后请求详情
        """
        state = self.node_states.get(node_id, _new_node_state(node_id))
        serialized_state = self._serialize_node_state(state)

        # 找出所有关联边
        related = []
        for edge in self.final_edges:
            if edge.get("u") == node_id or edge.get("v") == node_id:
                related.append(edge)

        # 构建时间线
        timeline = []
        for edge in related:
            role = "sender" if edge["u"] == node_id else "receiver"
            timeline.append({
                "time": edge["time"],
                "role": role,
                "counterparty": edge["v"] if role == "sender" else edge["u"],
                "amount": edge["amt"],
                "tag": edge["tag"],
                "status": edge.get("status", "success"),
            })

        return {
            "node_id": node_id,
            "current_state": serialized_state,
            "related_edges": related,
            "timeline": timeline,
        }

    def node_status_distribution(self):
        # type: () -> Dict[str, int]
        """
        统计各状态的节点数量（供前端面积图）

        输出：{ "active": 950, "frozen": 30, "suspended": 20 }
        """
        dist = Counter()
        for state in self.node_states.values():
            dist[state.get("status", "active")] += 1
        return dict(dist)

    def get_statistics(self):
        # type: () -> Dict[str, Any]
        """
        获取完整结算统计（供 pipeline_complete 消息和 CompletionCard）

        输出：
          {
            "total_edges": int,
            "normal_edges": int,
            "anomaly_edges": int,
            "blocked_edges": int,
            "total_amount_transferred": int,
            "anomaly_breakdown": { "anomaly_overdraft": 15, ... },
            "node_status_distribution": { "active": 950, ... },
            "first_event_time": str,
            "last_event_time": str,
            "active_time_blocks": int
          }
        """
        # 时间范围统计
        first_time = ""
        last_time = ""
        active_blocks = set()
        for edge in self.final_edges:
            t = edge.get("time", "")
            if t:
                if not first_time:
                    first_time = t
                last_time = t
                # 提取天标签作为 active block
                parts = t.split("_")
                if len(parts) >= 2:
                    active_blocks.add("{p}_{d}".format(p=parts[0], d=parts[1]))

        return {
            "total_edges": self._stats["total_processed"],
            "normal_edges": self._stats["normal_count"],
            "anomaly_edges": self._stats["anomaly_count"],
            "blocked_edges": self._stats["blocked_count"],
            "conflict_edges_removed": 0,  # 不再删除，都修正了
            "corrected_edges": self._stats["corrected_count"],
            "total_amount_transferred": self._stats["total_amount_transferred"],
            "anomaly_breakdown": dict(self._stats["anomaly_breakdown"]),
            "node_status_distribution": self.node_status_distribution(),
            "first_event_time": first_time,
            "last_event_time": last_time,
            "active_time_blocks": len(active_blocks),
        }

    def get_final_graph(self):
        # type: () -> Dict[str, Any]
        """
        获取完整的最终图数据（供导出和 pipeline_complete）

        输出：
          {
            "nodes": [{ id, final_balance, risk_level, status, ... }],
            "edges": [{ time, u, v, amt, tag, anomaly_reason, ... }],
            "statistics": { ... }
          }
        """
        nodes_list = []
        for node_id, state in self.node_states.items():
            nodes_list.append({
                "id": node_id,
                "final_balance": state.get("balance", 0),
                "risk_level": state.get("risk_level", "low"),
                "status": state.get("status", "active"),
                "transaction_count": state.get("transaction_count", 0),
                "anomaly_count": state.get("anomaly_count", 0),
            })

        return {
            "nodes": nodes_list,
            "edges": self.final_edges,
            "statistics": self.get_statistics(),
        }

    # ============================================================
    # 序列化辅助
    # ============================================================

    def _serialize_node_state(self, state):
        # type: (Dict[str, Any]) -> Dict[str, Any]
        """
        将节点状态序列化为 JSON 兼容格式

        主要处理：set → list 转换（JSON 不支持 set）
        """
        result = {}
        for k, v in state.items():
            if isinstance(v, set):
                result[k] = sorted(list(v))  # set → sorted list
            else:
                result[k] = v
        return result

    def get_all_node_states_serialized(self):
        # type: () -> Dict[str, Dict[str, Any]]
        """获取所有节点状态的 JSON 兼容副本"""
        return {
            nid: self._serialize_node_state(state)
            for nid, state in self.node_states.items()
        }
