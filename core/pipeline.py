# ============================================================
# SAGA CLI - 四阶段 Pipeline 编排器
# 用途：编排 Phase 1-4 的执行顺序，不含任何网络/WS/HTTP 逻辑
#       可被 saga_cli.py（命令行）和 server.py（网页版）共同调用
# ============================================================

import asyncio
import math
import random
import time
from collections import Counter
from typing import Dict, Any, List, Optional, Callable

import numpy as np

from config import (
    get_macro_block_label, get_total_macro_blocks, get_time_span_days,
    parse_macro_block_index,
)
from core.skeleton import SkeletonGenerator
from core.dispatcher import TaskDispatcher
from core.agent import SemanticAgent
from core.state_machine import GraphStateMachine
from rag import get_rules_for_scenario, get_scenario_hour_weights
from utils.logger import get_logger, log_event, clear_logs

logger = get_logger("saga.core.pipeline")


class SAGAPipeline:
    """
    SAGA 四阶段流水线统一编排器。

    使用方式：
        pipeline = SAGAPipeline(config, on_event=my_callback)
        result = asyncio.run(pipeline.run())

    参数:
        config: dict — 完整配置字典
        on_event: callable(event_type: str, data: dict) -> None
            可选的事件回调。CLI 传 print 函数，server.py 传 ws.send。
            不传则静默执行。
    """

    def __init__(self, config, on_event=None):
        # type: (Dict[str, Any], Optional[Callable]) -> None
        self.config = config
        self.on_event = on_event or (lambda t, d: None)
        self.timings = {}  # type: Dict[str, float]

    async def run(self):
        # type: () -> Dict[str, Any]
        """
        执行完整四阶段流水线。

        返回:
        {
            "nodes": [...], "edges": [...],
            "statistics": { ... },
            "timings": { "phase_s_ms", "phase_a1_ms", "phase_g_ms", "phase_a2_ms", "total_ms" }
        }
        """
        # 设置随机种子
        seed = self.config.get("seed")
        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)

        clear_logs()
        total_start = time.perf_counter()

        # === Phase S: 骨架生成 ===
        self.on_event("phase_start", {"phase": 1, "name": "Skeleton Generation"})
        t0 = time.perf_counter()
        skeleton = self._run_skeleton()
        self.timings["phase_s_ms"] = (time.perf_counter() - t0) * 1000
        self.on_event("skeleton_complete", {
            "nodes": len(skeleton["nodes"]),
            "edges": len(skeleton["macro_edges"]),
            "time_blocks": skeleton["metadata"]["total_time_blocks"],
        })

        # === Phase A1: 任务分发 ===
        self.on_event("phase_start", {"phase": 2, "name": "Task Dispatching"})
        t0 = time.perf_counter()
        tasks, dispatcher = self._run_dispatch(skeleton)
        self.timings["phase_a1_ms"] = (time.perf_counter() - t0) * 1000
        self.on_event("dispatch_complete", {"tasks": len(tasks)})

        # === Phase G: 语义注入 ===
        self.on_event("phase_start", {"phase": 3, "name": "Semantic Injection"})
        t0 = time.perf_counter()
        micro_edges = await self._run_injection(tasks)
        self.timings["phase_g_ms"] = (time.perf_counter() - t0) * 1000
        self.on_event("injection_complete", {"micro_edges": len(micro_edges)})

        # === Phase A2: 对齐结算 ===
        self.on_event("phase_start", {"phase": 4, "name": "Settlement"})
        t0 = time.perf_counter()
        final_graph = self._run_alignment(micro_edges, dispatcher)
        self.timings["phase_a2_ms"] = (time.perf_counter() - t0) * 1000

        self.timings["total_ms"] = (time.perf_counter() - total_start) * 1000

        # 附加 timings 到结果
        final_graph["timings"] = dict(self.timings)

        self.on_event("pipeline_complete", {
            "total_edges": final_graph["statistics"]["total_edges"],
            "anomaly_edges": final_graph["statistics"]["anomaly_edges"],
            "elapsed_sec": self.timings["total_ms"] / 1000,
        })

        return final_graph

    # ============================================================
    # Phase S: 骨架生成
    # ============================================================

    def _run_skeleton(self):
        # type: () -> Dict[str, Any]
        cfg = self.config
        gen = SkeletonGenerator()

        seed = cfg.get("seed")
        if seed is not None:
            gen.set_seed(seed)

        mode = cfg.get("skeleton_mode", "power_law")

        if mode == "random_er":
            # 消融实验 B：Erdős-Rényi 随机图替代幂律
            return self._generate_er_skeleton(gen, cfg)

        # 正常模式：Barabási-Albert 幂律图
        num_nodes = cfg.get("num_nodes", 1000)
        # 修复 #1: 必须传 num_edges！之前遗漏导致边数不可控
        num_edges = cfg.get("num_edges", num_nodes * 5)
        days = cfg.get("time_span_days", 30)
        gamma = cfg.get("power_law_gamma", 2.5)
        hub_ratio = cfg.get("hub_ratio", 0.1)
        block_unit = cfg.get("macro_block_unit", "day")
        micro_gran = cfg.get("micro_granularity", "minute")

        total_blocks = get_total_macro_blocks(days, "day", block_unit)

        return gen.generate_power_law_skeleton(
            num_nodes=num_nodes,
            num_edges=num_edges,       # 修复 #1: 传入边数
            time_blocks=total_blocks,
            gamma=gamma,
            hub_ratio=hub_ratio,
            macro_block_unit=block_unit,
            micro_granularity=micro_gran,
            burstiness=cfg.get("burstiness", 0.3),
        )

    def _generate_er_skeleton(self, gen, cfg):
        # type: (SkeletonGenerator, Dict) -> Dict[str, Any]
        """消融实验 B：Erdős-Rényi 随机图"""
        import igraph as ig

        n = cfg.get("num_nodes", 1000)
        days = cfg.get("time_span_days", 30)
        block_unit = cfg.get("macro_block_unit", "day")
        micro_gran = cfg.get("micro_granularity", "minute")
        total_blocks = get_total_macro_blocks(days, "day", block_unit)

        # 和 BA 模型匹配边密度：m=5 → 每节点约 5 条边
        m = 5
        p = min(1.0, (m * 2.0) / max(n - 1, 1))
        graph = ig.Graph.Erdos_Renyi(n=n, p=p, directed=True)
        raw_edges = graph.get_edgelist()

        # 复用骨架生成器的后处理逻辑
        node_ids = gen._generate_node_ids(n)
        time_assignments = gen._assign_macro_times(
            len(raw_edges), total_blocks, block_unit, cfg.get("burstiness", 0.3)
        )

        macro_edges = []
        for idx, (src, tgt) in enumerate(raw_edges):
            macro_edges.append({
                "edge_id": "E_{eid:05d}".format(eid=idx + 1),
                "source": node_ids[src],
                "target": node_ids[tgt],
                "macro_time": time_assignments[idx],
                "type": "transfer",
                "initial_tags": {},
            })

        degree_map = gen._compute_degree_map(raw_edges, node_ids, n)

        first_label = get_macro_block_label(1, block_unit)
        last_label = get_macro_block_label(total_blocks, block_unit)

        return {
            "nodes": node_ids,
            "macro_edges": macro_edges,
            "metadata": {
                "total_nodes": n,
                "total_edges": len(raw_edges),
                "time_span": "{f} to {l}".format(f=first_label, l=last_label),
                "total_time_blocks": total_blocks,
                "macro_block_unit": block_unit,
                "micro_granularity": micro_gran,
                "edges_per_block_avg": round(len(raw_edges) / max(total_blocks, 1), 2),
                "generator_type": "igraph_erdos_renyi",
                "gamma": 0,
                "hub_ratio": 0,
                "burstiness": cfg.get("burstiness", 0.3),
            },
            "degree_map": degree_map,
        }

    # ============================================================
    # Phase A1: 任务分发
    # ============================================================

    def _run_dispatch(self, skeleton):
        # type: (Dict[str, Any]) -> tuple
        cfg = self.config
        n = cfg.get("num_nodes", 1000)
        initial_balance = cfg.get("initial_balance", 1000)

        # 自定义初始余额函数：所有节点相同余额（可控实验用）
        def balance_fn(node_id, num_nodes):
            return initial_balance

        dispatcher = TaskDispatcher(num_nodes=n, initial_balance_fn=balance_fn)
        tasks = dispatcher.dispatch_from_skeleton(
            skeleton,
            micro_granularity=cfg.get("micro_granularity", "minute"),
        )

        # 消融实验 F：强制所有时间块余额已知（禁用 UNKNOWN 机制）
        # 这会导致 Agent 不再因余额未知而超支，anomaly_overdraft 大幅减少
        if cfg.get("force_known_balance", False):
            for task in tasks:
                ctx = task.get("context", {})
                if ctx.get("actor_balance") == "UNKNOWN":
                    ctx["actor_balance"] = initial_balance
                if ctx.get("target_balance") == "UNKNOWN":
                    ctx["target_balance"] = initial_balance

        return tasks, dispatcher

    # ============================================================
    # Phase G: 语义注入
    # ============================================================

    async def _run_injection(self, tasks):
        # type: (List[Dict]) -> List[Dict]
        cfg = self.config

        injection_mode = cfg.get("injection_mode", "llm")

        if injection_mode == "random_attr":
            # 消融实验 C：不调 LLM，随机属性
            return self._random_injection(tasks)

        # 正常模式：LLM Agent
        domain = cfg.get("domain", "finance")
        rag_level = cfg.get("rag_level", "full")

        # rag_level="none" → 消融实验 E：不注入 RAG 规则
        if rag_level == "none":
            rag_rules = ""
        else:
            rag_rules = get_rules_for_scenario(
                self._domain_to_scenario_id(domain), level=rag_level
            )

        hour_weights = get_scenario_hour_weights(self._domain_to_scenario_id(domain))
        use_mock = (cfg.get("llm_provider", "mock") == "mock")

        agent = SemanticAgent(
            rag_rules=rag_rules,
            use_mock=use_mock,
            hour_weights=hour_weights,
            seed=cfg.get("seed"),
            anomaly_rate=0.0,  # Agent 不标记异常，全部由代码控制
        )

        # ============================================================
        # 教授方案：anomaly 先生成，正常边边生边检查，到数就停
        # ============================================================
        target_edges = cfg.get("num_edges", len(tasks))
        anomaly_rate = cfg.get("anomaly_rate", 0.1)
        target_anomaly = int(round(target_edges * anomaly_rate))
        target_normal = target_edges - target_anomaly

        logger.info("边数控制: 目标总边数=%d, 异常=%d (%.1f%%), 正常=%d",
                     target_edges, target_anomaly, anomaly_rate * 100, target_normal)

        # 第一步：并发处理所有 Task，每个 Task 生成 1 条边
        all_micro_edges = await agent.process_tasks_batch(tasks)

        # 清除所有 LLM 可能返回的异常标记（代码精确控制，不信 LLM）
        for e in all_micro_edges:
            e["is_anomaly"] = False
            e["anomaly_type"] = ""

        # 按时间排序（保证时序正确性）
        all_micro_edges.sort(key=lambda e: e.get("micro_time", ""))

        # 第二步：精确截断到目标总边数
        if len(all_micro_edges) > target_edges:
            all_micro_edges = all_micro_edges[:target_edges]
        elif len(all_micro_edges) < target_edges:
            # 边数不够时，从已有边中复制并微调时间（保证边数精确）
            logger.warning("生成边数 %d < 目标 %d，补充边", len(all_micro_edges), target_edges)
            import random as _rand
            while len(all_micro_edges) < target_edges:
                donor = _rand.choice(all_micro_edges[:max(1, len(all_micro_edges))])
                new_edge = dict(donor)
                new_edge["properties"] = dict(donor.get("properties", {}))
                # 微调时间避免完全重复
                mt = new_edge.get("micro_time", "Day_1_12:00")
                if "_" in mt:
                    day_part = mt.rsplit("_", 1)[0]
                    h = _rand.randint(0, 23)
                    m = _rand.randint(0, 59)
                    new_edge["micro_time"] = "{d}_{h:02d}:{m:02d}".format(d=day_part, h=h, m=m)
                all_micro_edges.append(new_edge)
            all_micro_edges.sort(key=lambda e: e.get("micro_time", ""))

        # 第三步：随机选 target_anomaly 条标记为异常（异常数量固定不变）
        import random as _rand
        if cfg.get("seed") is not None:
            _rand.seed(cfg["seed"] + 777)  # 异常选择用不同偏移种子

        anomaly_types = ["anomaly_structuring", "anomaly_large_amount",
                         "anomaly_rapid_movement", "anomaly_unusual_pattern",
                         "anomaly_high_frequency", "anomaly_round_trip"]

        indices = list(range(len(all_micro_edges)))
        _rand.shuffle(indices)
        for i in indices[:target_anomaly]:
            e = all_micro_edges[i]
            e["is_anomaly"] = True
            atype = _rand.choice(anomaly_types)
            e["anomaly_type"] = atype

            props = e.get("properties", {})

            # 代码扭曲参数（让异常边的数据确实异常）
            if atype == "anomaly_large_amount":
                e["amount"] = e.get("amount", 1000) * _rand.randint(5, 20)
            elif atype == "anomaly_structuring":
                e["amount"] = _rand.choice([9999, 9998, 9990, 4999])
            elif atype == "anomaly_unusual_pattern":
                mt = e.get("micro_time", "")
                if "_" in mt:
                    day_part = mt.rsplit("_", 1)[0]
                    h = _rand.choice([1, 2, 3, 4])
                    m = _rand.randint(0, 59)
                    e["micro_time"] = "{d}_{h:02d}:{m:02d}".format(d=day_part, h=h, m=m)
            elif atype == "anomaly_high_frequency":
                e["amount"] = _rand.randint(50, 500)

            props["risk_score"] = round(_rand.uniform(0.6, 1.0), 3)
            props["anomaly_reason"] = "Code-marked: " + atype
            e["properties"] = props

        logger.info("边数控制结果: 总=%d, 异常=%d, 正常=%d (目标: %d/%d/%d)",
                     len(all_micro_edges), target_anomaly,
                     len(all_micro_edges) - target_anomaly,
                     target_edges, target_anomaly, target_normal)

        return all_micro_edges

    def _random_injection(self, tasks):
        # type: (List[Dict]) -> List[Dict]
        """消融实验 C：不调 LLM，完全随机的属性"""
        rng = random.Random(self.config.get("seed"))
        micro_edges = []
        for task in tasks:
            ctx = task.get("context", {})
            day = ctx.get("current_day", "Day_1")
            h = rng.randint(0, 23)
            m = rng.randint(0, 59)
            micro_edges.append({
                "micro_time": "{d}_{h:02d}:{m:02d}".format(d=day, h=h, m=m),
                "source": ctx.get("actor", ""),
                "target": ctx.get("target", ""),
                "amount": rng.randint(1, 10000),
                "properties": {"transaction_type": "random", "risk_score": 0.0},
            })
        return micro_edges

    # ============================================================
    # Phase A2: 对齐结算
    # ============================================================

    def _run_alignment(self, micro_edges, dispatcher):
        # type: (List[Dict], TaskDispatcher) -> Dict[str, Any]
        cfg = self.config

        if cfg.get("skip_alignment", False):
            # 消融实验 D：跳过 Phase 4，所有边标记为 unverified
            nodes_list = []
            for nid, bal in dispatcher.get_initial_balances().items():
                nodes_list.append({
                    "id": nid, "final_balance": bal,
                    "risk_level": "low", "status": "active",
                    "transaction_count": 0, "anomaly_count": 0,
                })
            edges_out = []
            for e in micro_edges:
                edges_out.append({
                    "time": e.get("micro_time", ""),
                    "u": e.get("source", ""),
                    "v": e.get("target", ""),
                    "amt": e.get("amount", 0),
                    "tag": "unverified",
                    "anomaly_reason": "",
                    "status": "unverified",
                    "properties": e.get("properties", {}),
                })
            return {
                "nodes": nodes_list,
                "edges": edges_out,
                "statistics": {
                    "total_nodes": len(nodes_list),
                    "total_edges": len(edges_out),
                    "normal_edges": 0,
                    "anomaly_edges": 0,
                    "blocked_edges": 0,
                    "total_amount_transferred": 0,
                    "anomaly_breakdown": {},
                },
            }

        # 正常模式：状态机修正（不删边，改金额）
        initial_balances = dispatcher.get_initial_balances()
        sm = GraphStateMachine(initial_balances=initial_balances)
        sm.process_all_edges(micro_edges)
        return sm.get_final_graph()

    # ============================================================
    # 辅助
    # ============================================================

    @staticmethod
    def _domain_to_scenario_id(domain):
        # type: (str) -> str
        mapping = {
            "finance": "finance_aml",
            "network": "network_ids",
            "cyber": "cyber_apt",
            "traffic": "traffic",
        }
        return mapping.get(domain, domain)
