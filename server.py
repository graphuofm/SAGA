# ============================================================
# SAGA - WebSocket + HTTP 服务器（完整版）
# 第 6 批 / 共 10 批
# 用途：SAGA 后端服务入口，承载全部前后端通信：
#       - WebSocket：流水线控制、实时数据推送、交互指令
#       - HTTP：/estimate 预估、/download 下载、/download-log 日志
#       - 完整 4 阶段 Pipeline 编排（Phase 1→2→3→4）
# Pipeline 阶段：贯穿所有阶段的服务层
# ============================================================

import asyncio
import os
import sys
import time
import traceback
from typing import Dict, Any, List, Optional

import websockets
from aiohttp import web

from config import (
    WS_HOST, WS_PORT, HTTP_HOST, HTTP_PORT,
    OUTPUT_DIR, LLM_BACKEND,
    get_full_config, validate_time_config, estimate_generation,
)
from core.skeleton import SkeletonGenerator
from core.dispatcher import TaskDispatcher
from core.state_machine import GraphStateMachine
from core.agent import SemanticAgent
from rag import get_rules_for_scenario, get_rule_preview, get_scenario_hour_weights
from rag.parameter_inferrer import infer_parameters
from utils.logger import (
    get_logger, log_event, clear_logs,
    progress_tracker,
)
from utils.export import package_zip, generate_log_json, to_json

# orjson 加速
try:
    import orjson
    def _dumps(obj):
        # type: (Any) -> str
        return orjson.dumps(obj, default=str).decode("utf-8")
except ImportError:
    import json
    def _dumps(obj):
        # type: (Any) -> str
        return json.dumps(obj, ensure_ascii=False, default=str)

logger = get_logger("saga.server")


# ============================================================
# Pipeline 服务器
# ============================================================

class PipelineServer:
    """
    SAGA 后端服务器，管理完整 Pipeline 生命周期

    职责：
    1. WebSocket 接收前端指令并分发处理
    2. 编排 Phase 1→2→3→4 顺序执行
    3. 实时推送生成数据和进度给前端
    4. 支持 pause / resume / stop 控制
    5. 支持运行中注入事件
    6. HTTP 提供预估和文件下载接口
    """

    def __init__(self):
        # type: () -> None
        # --- Pipeline 状态 ---
        self.pipeline_state = "idle"  # idle/running/paused/stopped/completed/error
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # 初始不暂停
        self._is_running = False
        self._stop_requested = False

        # --- 运行配置快照（每次 start 时记录）---
        self._config = {}  # type: Dict[str, Any]

        # --- 核心组件（每次 start 时创建）---
        self._skeleton = None    # type: Optional[Dict]
        self._dispatcher = None  # type: Optional[TaskDispatcher]
        self._agent = None       # type: Optional[SemanticAgent]
        self._state_machine = None  # type: Optional[GraphStateMachine]

        # --- Phase 3 产物 ---
        self._all_micro_edges = []  # type: List[Dict]

        # --- 已连接的 WebSocket 客户端 ---
        self._clients = set()

        # --- Pipeline 计时 ---
        self._start_time = 0.0

        # --- 注入事件 ---
        self._injected_events = []  # type: List[Dict]

        # --- 消息聚合缓冲（避免高频推送压垮浏览器）---
        # CONFIG: 每 WS_BATCH_SIZE 条边打包推送一次
        self._ws_batch_size = 50
        self._edge_buffer = []  # type: List[Dict]

    # ============================================================
    # WebSocket 消息处理
    # ============================================================

    async def _handle_ws(self, websocket):
        """WebSocket 连接处理主循环"""
        self._clients.add(websocket)
        client_addr = websocket.remote_address
        logger.info("WebSocket 客户端连接: %s", client_addr)

        # 发送欢迎消息 + 当前状态
        await self._send(websocket, {
            "type": "connected",
            "data": {
                "status": self.pipeline_state,
                "server_version": "SAGA-1.0",
                "config": get_full_config(),
            }
        })

        try:
            async for raw_msg in websocket:
                try:
                    msg = orjson.loads(raw_msg) if 'orjson' in sys.modules else __import__('json').loads(raw_msg)
                except Exception:
                    await self._send(websocket, {
                        "type": "error", "data": {"message": "Invalid JSON"}
                    })
                    continue
                await self._dispatch_message(websocket, msg)
        except websockets.exceptions.ConnectionClosed:
            logger.info("WebSocket 客户端断开: %s", client_addr)
        finally:
            self._clients.discard(websocket)

    async def _dispatch_message(self, ws, msg):
        # type: (Any, Dict[str, Any]) -> None
        """根据消息类型分发到对应处理函数"""
        msg_type = msg.get("type", "")

        if msg_type == "start_pipeline":
            # 启动流水线（在后台任务中运行，不阻塞 WS 消息循环）
            asyncio.ensure_future(self._run_pipeline(msg.get("config", {})))

        elif msg_type == "pause_pipeline":
            self._pause_event.clear()
            self.pipeline_state = "paused"
            await self._broadcast({
                "type": "status",
                "data": {"status": "paused",
                         "_progress": progress_tracker.get_progress()}
            })

        elif msg_type == "resume_pipeline":
            self._pause_event.set()
            self.pipeline_state = "running"
            await self._broadcast({
                "type": "status",
                "data": {"status": "running"}
            })

        elif msg_type == "stop_pipeline":
            self._stop_requested = True
            self._pause_event.set()  # 如果暂停中，先恢复以便退出循环
            # pipeline 循环检测到 _stop_requested 后会自行收尾

        elif msg_type == "inject_event":
            await self._handle_inject_event(msg.get("event", {}))

        elif msg_type == "get_node_detail":
            await self._handle_get_node_detail(ws, msg.get("node_id", ""))

        elif msg_type == "infer_parameters":
            await self._handle_infer_parameters(ws, msg)

        elif msg_type == "get_rag_preview":
            await self._handle_rag_preview(ws, msg.get("scenario", ""))

        elif msg_type == "preview_degree_dist":
            await self._handle_degree_preview(ws, msg)

        elif msg_type == "get_config":
            await self._send(ws, {
                "type": "config",
                "data": get_full_config()
            })

        else:
            logger.warning("未知消息类型: %s", msg_type)

    # ============================================================
    # Pipeline 主流程
    # ============================================================

    async def _run_pipeline(self, user_config):
        # type: (Dict[str, Any]) -> None
        """
        完整 Pipeline 编排：Phase 1 → 2 → 3 → 4

        在后台 asyncio Task 中运行，不阻塞 WebSocket 消息处理。
        每个阶段之间检查 pause / stop 状态。
        """
        # --- 初始化 ---
        self._is_running = True
        self._stop_requested = False
        self._pause_event.set()
        self.pipeline_state = "running"
        self._start_time = time.perf_counter()
        self._all_micro_edges = []
        self._injected_events = []
        clear_logs()

        # 合并用户配置和默认配置
        self._config = get_full_config(user_config)

        # 校验时间配置
        ok, err = validate_time_config(
            self._config.get("time_span_value", 30),
            self._config.get("time_span_unit", "day"),
            self._config.get("macro_block_unit", "day"),
            self._config.get("micro_granularity", "minute"),
        )
        if not ok:
            await self._broadcast({
                "type": "error",
                "data": {"message": "Invalid time config: {e}".format(e=err)}
            })
            self.pipeline_state = "error"
            self._is_running = False
            return

        log_event(0, "pipeline_start", "Pipeline 启动", {"config": self._config})
        await self._broadcast({
            "type": "status",
            "data": {"status": "running", "config": self._config}
        })

        try:
            # === Phase 1: 骨架生成 ===
            await self._run_phase1()
            if self._stop_requested:
                await self._handle_stop()
                return

            # === Phase 2: 任务调度 ===
            await self._run_phase2()
            if self._stop_requested:
                await self._handle_stop()
                return

            # === Phase 3: 语义注入 ===
            await self._run_phase3()
            if self._stop_requested:
                await self._handle_stop()
                return

            # === Phase 4: 对齐结算 ===
            await self._run_phase4()
            if self._stop_requested:
                await self._handle_stop()
                return

            # === 完成 ===
            elapsed = time.perf_counter() - self._start_time
            final_graph = self._state_machine.get_final_graph()

            # 计算完整统计指标（度分布拟合、聚类系数、时间分布等）
            from utils.stats import compute_statistics
            full_stats = compute_statistics(final_graph, config=self._config)
            # 合并 state_machine 原始统计和 stats.py 的高级统计
            merged_stats = dict(final_graph["statistics"])
            merged_stats.update(full_stats)
            final_graph["statistics"] = merged_stats

            await self._broadcast({
                "type": "pipeline_complete",
                "data": {
                    "final_graph": {
                        "nodes": final_graph["nodes"],
                        "statistics": merged_stats,
                        "total_edges": len(final_graph["edges"]),
                    },
                    "elapsed_seconds": round(elapsed, 2),
                }
            })

            self.pipeline_state = "completed"
            log_event(0, "pipeline_complete",
                      "Pipeline 完成: {t:.1f}s".format(t=elapsed))

        except Exception as e:
            logger.error("Pipeline 异常: %s\n%s", str(e), traceback.format_exc())
            self.pipeline_state = "error"
            await self._broadcast({
                "type": "error",
                "data": {"message": str(e), "phase": progress_tracker.get_progress().get("current_phase")}
            })
        finally:
            self._is_running = False

    # ============================================================
    # 各阶段实现
    # ============================================================

    async def _run_phase1(self):
        """Phase 1: 骨架生成"""
        await self._broadcast({"type": "phase_start", "data": {"phase": 1, "name": "Skeleton Generation"}})
        progress_tracker.set_phase(1)

        gen = SkeletonGenerator()
        # 在线程池中执行 CPU 密集任务，避免阻塞事件循环
        loop = asyncio.get_event_loop()
        self._skeleton = await loop.run_in_executor(
            None, gen.generate_from_config, self._config
        )

        # 推送骨架数据
        await self._broadcast({
            "type": "skeleton_complete",
            "data": {
                "nodes": self._skeleton["nodes"],
                "macro_edges": self._skeleton["macro_edges"],
                "metadata": self._skeleton["metadata"],
                "degree_map": self._skeleton["degree_map"],
            }
        })

    async def _run_phase2(self):
        """Phase 2: 任务调度"""
        await self._check_pause_stop()
        await self._broadcast({"type": "phase_start", "data": {"phase": 2, "name": "Task Dispatching"}})
        progress_tracker.set_phase(2)

        num_nodes = self._config.get("num_nodes", 1000)
        self._dispatcher = TaskDispatcher(num_nodes=num_nodes)

        loop = asyncio.get_event_loop()
        tasks = await loop.run_in_executor(
            None, self._dispatcher.dispatch_from_skeleton,
            self._skeleton,
            self._config.get("micro_granularity", "minute"),
        )
        self._tasks = tasks

        stats = self._dispatcher.get_dispatch_stats(tasks)
        await self._broadcast({
            "type": "tasks_complete",
            "data": {"stats": stats}
        })

    async def _run_phase3(self):
        """Phase 3: 语义注入（Agent 生成微观边）— 并行版 + anomaly 先生成"""
        await self._check_pause_stop()
        await self._broadcast({"type": "phase_start", "data": {"phase": 3, "name": "Semantic Injection"}})

        # 加载 RAG 规则
        scenario_id = self._config.get("scenario", "finance_aml") or "finance_aml"
        rag_rules = get_rules_for_scenario(scenario_id, level="full")
        hour_weights = get_scenario_hour_weights(scenario_id)

        use_mock = (self._config.get("llm_backend", LLM_BACKEND).lower() == "mock")
        self._agent = SemanticAgent(
            rag_rules=rag_rules,
            use_mock=use_mock,
            injected_events=self._injected_events,
            hour_weights=hour_weights,
            anomaly_rate=0.0,  # Agent 不标异常，全部由代码控制
        )

        total_tasks = len(self._tasks)
        progress_tracker.set_phase(
            3,
            total_expected=total_tasks,
            total_blocks=self._config.get("total_macro_blocks"),
        )

        # 修复 #19: Phase 3 推送中间进度（每 10% 推送一次）
        await self._broadcast({
            "type": "progress",
            "data": {"_progress": progress_tracker.get_progress()}
        })

        # 并行处理所有任务
        self._all_micro_edges = await self._agent.process_tasks_batch(self._tasks)

        # === 教授方案：anomaly 先生成，边数精确控制 ===
        target_edges = self._config.get("num_edges", len(self._all_micro_edges))
        anomaly_rate = self._config.get("anomaly_rate", 0.1)
        target_anomaly = int(round(target_edges * anomaly_rate))
        target_normal = target_edges - target_anomaly

        # 清除 LLM 标记
        for e in self._all_micro_edges:
            e["is_anomaly"] = False
            e["anomaly_type"] = ""

        # 按时间排序
        self._all_micro_edges.sort(key=lambda e: e.get("micro_time", ""))

        # 精确截断到目标边数
        if len(self._all_micro_edges) > target_edges:
            self._all_micro_edges = self._all_micro_edges[:target_edges]
        elif len(self._all_micro_edges) < target_edges:
            # 不够时补充
            import random as _rand
            while len(self._all_micro_edges) < target_edges:
                donor = _rand.choice(self._all_micro_edges[:max(1, len(self._all_micro_edges))])
                new_edge = dict(donor)
                new_edge["properties"] = dict(donor.get("properties", {}))
                mt = new_edge.get("micro_time", "Day_1_12:00")
                if "_" in mt:
                    day_part = mt.rsplit("_", 1)[0]
                    h = _rand.randint(0, 23)
                    m = _rand.randint(0, 59)
                    new_edge["micro_time"] = "{d}_{h:02d}:{m:02d}".format(d=day_part, h=h, m=m)
                self._all_micro_edges.append(new_edge)
            self._all_micro_edges.sort(key=lambda e: e.get("micro_time", ""))

        # 随机选 target_anomaly 条标记异常（异常数量固定）
        import random as _rand
        anomaly_types = ["anomaly_structuring", "anomaly_large_amount",
                         "anomaly_rapid_movement", "anomaly_unusual_pattern",
                         "anomaly_high_frequency", "anomaly_round_trip"]
        indices = list(range(len(self._all_micro_edges)))
        _rand.shuffle(indices)
        for i in indices[:target_anomaly]:
            e = self._all_micro_edges[i]
            e["is_anomaly"] = True
            atype = _rand.choice(anomaly_types)
            e["anomaly_type"] = atype
            e.setdefault("properties", {})["anomaly_reason"] = "Code-marked: " + atype
            e.setdefault("properties", {})["risk_score"] = round(_rand.uniform(0.6, 1.0), 3)

        logger.info("边数控制: 总=%d, 异常=%d, 正常=%d (目标: %d/%d/%d)",
                     len(self._all_micro_edges), target_anomaly,
                     len(self._all_micro_edges) - target_anomaly,
                     target_edges, target_anomaly, target_normal)

        # 推送完成
        await self._broadcast({
            "type": "progress",
            "data": {"_progress": progress_tracker.get_progress()}
        })

        agent_stats = self._agent.get_stats()
        await self._broadcast({
            "type": "injection_complete",
            "data": {
                "total_edges": len(self._all_micro_edges),
                "stats": agent_stats,
            }
        })

    async def _run_phase4(self):
        """Phase 4: snapshot 握手结算 + 逐条推送"""
        await self._check_pause_stop()
        await self._broadcast({"type": "phase_start", "data": {"phase": 4, "name": "Settlement"}})

        initial_balances = self._dispatcher.get_initial_balances()
        self._state_machine = GraphStateMachine(initial_balances=initial_balances)

        # 在线程池中执行完整结算（CPU 密集）
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, self._state_machine.process_all_edges, self._all_micro_edges
        )

        # 结算完成后，逐批推送结果给前端（用于图渲染和回放）
        settled = self._state_machine.final_edges
        total = len(settled)
        progress_tracker.set_phase(4, total_expected=total)

        self._edge_buffer = []
        for idx, final_edge in enumerate(settled):
            src = final_edge.get("u", "")
            tgt = final_edge.get("v", "")

            # 节点状态快照
            node_snap = {}
            if src in self._state_machine.node_states:
                node_snap[src] = self._state_machine._serialize_node_state(
                    self._state_machine.node_states[src])
            if tgt in self._state_machine.node_states:
                node_snap[tgt] = self._state_machine._serialize_node_state(
                    self._state_machine.node_states[tgt])

            self._edge_buffer.append({"edge": final_edge, "node_states": node_snap})

            if len(self._edge_buffer) >= self._ws_batch_size:
                await self._flush_edge_buffer("settled_edge_batch")

            # 异常边单独推送
            if final_edge.get("tag", "normal") != "normal":
                await self._broadcast({
                    "type": "anomaly_detected",
                    "data": final_edge,
                })

            progress_tracker.update(edge_index=idx + 1)
            if (idx + 1) % 200 == 0 or idx == total - 1:
                await self._broadcast({
                    "type": "progress",
                    "data": {"_progress": progress_tracker.get_progress()}
                })

        await self._flush_edge_buffer("settled_edge_batch")

    # ============================================================
    # 控制辅助
    # ============================================================

    async def _check_pause_stop(self):
        """检查暂停/停止标志，暂停时阻塞直到恢复"""
        await self._pause_event.wait()

    async def _handle_stop(self):
        """处理停止请求：保留已有数据，推送部分结果"""
        self.pipeline_state = "stopped"
        elapsed = time.perf_counter() - self._start_time

        await self._broadcast({
            "type": "status",
            "data": {"status": "stopped"}
        })

        # 如果 Phase 4 已有部分结算结果，推送
        if self._state_machine and self._state_machine.final_edges:
            final_graph = self._state_machine.get_final_graph()
            await self._broadcast({
                "type": "pipeline_complete",
                "data": {
                    "final_graph": {
                        "nodes": final_graph["nodes"],
                        "statistics": final_graph["statistics"],
                        "total_edges": len(final_graph["edges"]),
                    },
                    "elapsed_seconds": round(elapsed, 2),
                    "partial": True,
                }
            })

        self._is_running = False
        log_event(0, "pipeline_stopped", "Pipeline 被用户终止")

    async def _flush_edge_buffer(self, msg_type):
        """将缓冲区中的边批量推送给前端"""
        if not self._edge_buffer:
            return
        await self._broadcast({
            "type": msg_type,
            "data": {
                "edges": self._edge_buffer,
                "count": len(self._edge_buffer),
                "_progress": progress_tracker.get_progress(),
            }
        })
        self._edge_buffer = []

    # ============================================================
    # 交互指令处理
    # ============================================================

    async def _handle_inject_event(self, event):
        # type: (Dict[str, Any]) -> None
        """处理用户注入事件"""
        scope = event.get("scope", "global")

        if scope == "targeted" and self._state_machine:
            # 定向事件：直接修改节点状态
            target_node = event.get("target_node", "")
            action = event.get("action", "")
            if action == "freeze" and target_node in self._state_machine.node_states:
                self._state_machine.node_states[target_node]["status"] = "frozen"
                self._state_machine.node_states[target_node]["risk_level"] = "frozen"
                log_event(0, "node_frozen",
                          "用户冻结节点: {n}".format(n=target_node))

        # 全局事件：追加到 Agent 上下文
        self._injected_events.append(event)
        if self._agent:
            self._agent.add_injected_event(event)

        event_id = "EVT_{t}".format(t=int(time.time() * 1000))
        await self._broadcast({
            "type": "event_injected",
            "data": {
                "event_id": event_id,
                "scope": scope,
                "target_node": event.get("target_node", ""),
                "status": "applied",
            }
        })

    async def _handle_get_node_detail(self, ws, node_id):
        # type: (Any, str) -> None
        """处理节点详情请求"""
        if not self._state_machine:
            await self._send(ws, {
                "type": "node_detail",
                "data": {"node_id": node_id, "error": "State machine not initialized"}
            })
            return

        detail = self._state_machine.get_node_detail(node_id)
        await self._send(ws, {
            "type": "node_detail",
            "data": detail,
        })

    async def _handle_infer_parameters(self, ws, msg):
        # type: (Any, Dict) -> None
        """处理参数推断请求"""
        scenario_id = msg.get("scenario", "")
        custom_rules = msg.get("custom_rules", "")

        if custom_rules:
            rules_text = custom_rules
        else:
            rules_text = get_rules_for_scenario(scenario_id, level="full")

        # 在线程池中执行（可能调 LLM）
        loop = asyncio.get_event_loop()
        params = await loop.run_in_executor(
            None, infer_parameters, rules_text, scenario_id
        )

        await self._send(ws, {
            "type": "inferred_parameters",
            "data": {
                "scenario": scenario_id,
                "parameters": params,
            }
        })

    async def _handle_rag_preview(self, ws, scenario_id):
        # type: (Any, str) -> None
        """处理 RAG 规则预览请求"""
        preview = get_rule_preview(scenario_id)
        await self._send(ws, {
            "type": "rag_preview",
            "data": preview,
        })

    async def _handle_degree_preview(self, ws, msg):
        # type: (Any, Dict) -> None
        """处理度分布预览请求"""
        gamma = msg.get("gamma", 2.5)
        num_nodes = msg.get("num_nodes", 1000)

        points = SkeletonGenerator.preview_degree_distribution(gamma, num_nodes)
        await self._send(ws, {
            "type": "degree_dist_preview",
            "data": {"points": points, "gamma": gamma, "num_nodes": num_nodes},
        })

    # ============================================================
    # WebSocket 通信辅助
    # ============================================================

    async def _send(self, ws, msg):
        # type: (Any, Dict) -> None
        """发送消息到单个客户端"""
        try:
            await ws.send(_dumps(msg))
        except websockets.exceptions.ConnectionClosed:
            self._clients.discard(ws)

    async def _broadcast(self, msg):
        # type: (Dict) -> None
        """广播消息到所有已连接客户端"""
        if not self._clients:
            return
        data = _dumps(msg)
        dead = set()
        for ws in self._clients:
            try:
                await ws.send(data)
            except websockets.exceptions.ConnectionClosed:
                dead.add(ws)
        self._clients -= dead

    # ============================================================
    # HTTP 路由
    # ============================================================

    def _setup_http_routes(self, app):
        # type: (web.Application) -> None
        """注册 HTTP 路由"""
        app.router.add_post("/estimate", self._http_estimate)
        app.router.add_get("/download", self._http_download)
        app.router.add_get("/download-log", self._http_download_log)
        app.router.add_get("/health", self._http_health)
        # CORS 预检
        app.router.add_route("OPTIONS", "/{path:.*}", self._http_cors_preflight)

    async def _http_cors_preflight(self, request):
        """CORS 预检请求处理"""
        return web.Response(headers=_cors_headers())

    async def _http_health(self, request):
        """健康检查"""
        return web.json_response(
            {"status": "ok", "pipeline_state": self.pipeline_state},
            headers=_cors_headers()
        )

    async def _http_estimate(self, request):
        """POST /estimate — 预估生成时间和文件大小"""
        try:
            body = await request.json()
        except Exception:
            return web.json_response(
                {"error": "Invalid JSON"}, status=400, headers=_cors_headers())

        result = estimate_generation(
            num_nodes=body.get("num_nodes", 1000),
            num_edges=body.get("num_edges", 5000),
            mode=body.get("mode", "mock"),
            formats=body.get("formats", ["json"]),
        )
        return web.json_response(result, headers=_cors_headers())

    async def _http_download(self, request):
        """GET /download — 下载生成结果 ZIP"""
        if not self._state_machine:
            return web.json_response(
                {"error": "No data available"}, status=404, headers=_cors_headers())

        # 解析查询参数
        formats = request.query.get("formats", "csv,json").split(",")
        properties = request.query.get("properties", "")
        # 过滤掉空字符串，None 表示不过滤（输出所有核心列）
        selected_props = [p for p in properties.split(",") if p.strip()] or None

        final_graph = self._state_machine.get_final_graph()
        zip_bytes = package_zip(
            final_graph, formats, selected_props, self._config
        )

        return web.Response(
            body=zip_bytes,
            content_type="application/zip",
            headers={
                "Content-Disposition": "attachment; filename=saga_output.zip",
                **_cors_headers(),
            }
        )

    async def _http_download_log(self, request):
        """GET /download-log — 下载运行日志 JSON"""
        log_bytes = generate_log_json(self._config)
        return web.Response(
            body=log_bytes,
            content_type="application/json",
            headers={
                "Content-Disposition": "attachment; filename=saga_run_log.json",
                **_cors_headers(),
            }
        )


# ============================================================
# CORS 辅助
# ============================================================

def _cors_headers():
    # type: () -> Dict[str, str]
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }


# ============================================================
# 启动入口
# ============================================================

async def main():
    """启动 WebSocket 和 HTTP 双服务"""
    server = PipelineServer()

    # --- 启动 WebSocket 服务 ---
    ws_server = await websockets.serve(
        server._handle_ws,
        WS_HOST,
        WS_PORT,
        ping_interval=30,     # 每 30 秒发 ping 保活
        ping_timeout=10,      # 10 秒未 pong 视为断开
        max_size=10 * 1024 * 1024,  # 最大消息 10MB
        close_timeout=5,
    )
    logger.info("WebSocket 服务已启动: ws://%s:%d", WS_HOST, WS_PORT)

    # --- 启动 HTTP 服务 ---
    app = web.Application()
    server._setup_http_routes(app)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, HTTP_HOST, HTTP_PORT)
    await site.start()
    logger.info("HTTP 服务已启动: http://%s:%d", HTTP_HOST, HTTP_PORT)

    logger.info("SAGA 后端就绪，等待前端连接...")
    logger.info("  WebSocket: ws://%s:%d", WS_HOST, WS_PORT)
    logger.info("  HTTP:      http://%s:%d", HTTP_HOST, HTTP_PORT)
    logger.info("  LLM 后端:  %s", LLM_BACKEND)

    # 永久运行
    await asyncio.Future()


if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("服务器已关闭")
