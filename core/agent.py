# ============================================================
# SAGA - Phase 3: 语义注入 Agent（Semantic Agent）
# 第 4 批 / 共 10 批
# 用途：接收 Phase 2 的 Task 列表，结合 RAG 行业规则，
#       通过 LLM（或 Mock）为每条宏观边生成 2~5 条微观时序边
#       每条微观边带有精确的 micro_time、金额、属性等语义信息
# Pipeline 阶段：Phase 3（语义后附 — RAG + LLM 注入）
# ============================================================

import asyncio
import math
import random
import re
import time
from typing import Dict, Any, List, Optional, Tuple

from config import (
    LLM_BACKEND, OLLAMA_BASE_URL, OLLAMA_MODEL,
    OPENAI_BASE_URL, OPENAI_API_KEY, OPENAI_MODEL,
    LLM_TEMPERATURE, LLM_MAX_RETRIES, LLM_TIMEOUT_SECONDS,
    AGENT_CONCURRENCY, AGENT_BATCH_SIZE,
    DEFAULT_MICRO_GRANULARITY,
    parse_micro_time_key,
)
from utils.logger import get_logger, log_event, log_agent_trace, progress_tracker

logger = get_logger("saga.core.agent")


# ============================================================
# LLM 统一调用器（LLMCaller）
# 支持 Ollama / OpenAI / vLLM / Mock 四种后端
# 通过 .env 的 SAGA_LLM_BACKEND 切换
# ============================================================

class LLMCaller:
    """
    LLM 统一调用抽象层

    所有 LLM 调用都经过此类，屏蔽不同后端的 API 差异。
    支持的后端：
      - ollama: 调用本地 Ollama HTTP API
      - openai: 调用 OpenAI 兼容 API（也适配 vLLM）
      - vllm: 同 openai（vLLM 提供 OpenAI 兼容接口）
      - mock: 不调 LLM，返回空字符串（由 Agent 自行生成）

    所有地址、模型名、API Key 从 .env 读取，不硬编码。
    """

    def __init__(self, backend=None):
        # type: (Optional[str]) -> None
        self.backend = (backend or LLM_BACKEND).lower()
        logger.info("LLMCaller 初始化: backend=%s", self.backend)

    async def call(self, prompt, system_prompt=""):
        # type: (str, str) -> str
        """
        异步调用 LLM 并返回文本响应

        输入：
          prompt: 用户 prompt 文本
          system_prompt: 可选的系统 prompt
        输出：
          LLM 返回的文本字符串
        调用时机：SemanticAgent._call_llm() 内部

        错误处理：重试 LLM_MAX_RETRIES 次，全部失败返回空字符串
        """
        if self.backend == "mock":
            return ""

        for attempt in range(LLM_MAX_RETRIES):
            try:
                if self.backend == "ollama":
                    return await self._call_ollama(prompt, system_prompt)
                elif self.backend in ("openai", "vllm"):
                    return await self._call_openai(prompt, system_prompt)
                else:
                    logger.warning("未知 LLM 后端: %s，回退到 mock", self.backend)
                    return ""
            except Exception as e:
                logger.warning("LLM 调用失败 (attempt %d/%d): %s",
                               attempt + 1, LLM_MAX_RETRIES, str(e))
                if attempt < LLM_MAX_RETRIES - 1:
                    # 指数退避等待
                    await asyncio.sleep(min(2 ** attempt, 10))

        logger.error("LLM 调用全部失败，返回空响应")
        return ""

    async def _call_ollama(self, prompt, system_prompt):
        # type: (str, str) -> str
        """
        调用 Ollama HTTP API

        接口：POST {OLLAMA_BASE_URL}/api/generate
        文档：https://github.com/ollama/ollama/blob/main/docs/api.md
        """
        import aiohttp

        url = "{base}/api/generate".format(base=OLLAMA_BASE_URL.rstrip("/"))
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "system": system_prompt,
            "stream": False,
            "options": {
                "temperature": LLM_TEMPERATURE,
            },
        }

        timeout = aiohttp.ClientTimeout(total=LLM_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError("Ollama HTTP {s}: {t}".format(s=resp.status, t=text[:200]))
                data = await resp.json()
                return data.get("response", "")

    async def _call_openai(self, prompt, system_prompt):
        # type: (str, str) -> str
        """
        调用 OpenAI 兼容 API（适配 OpenAI / vLLM / LiteLLM 等）

        接口：POST {OPENAI_BASE_URL}/chat/completions
        """
        import aiohttp

        url = "{base}/chat/completions".format(base=OPENAI_BASE_URL.rstrip("/"))
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": OPENAI_MODEL,
            "messages": messages,
            "temperature": LLM_TEMPERATURE,
            "max_tokens": 1024,  # 修复 #7: 512 可能导致 JSON 被截断
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer {key}".format(key=OPENAI_API_KEY),
        }

        timeout = aiohttp.ClientTimeout(total=LLM_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError("OpenAI HTTP {s}: {t}".format(s=resp.status, t=text[:200]))
                data = await resp.json()
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "")
                return ""


# ============================================================
# 时间加权采样器（Mock 模式用）
# 根据 RAG 规则中的时间模式生成符合阵发性的时间戳
# ============================================================

# 默认时间段权重（金融场景）
# CONFIG: 第5批 RAG 规则可覆盖此权重表
_DEFAULT_HOUR_WEIGHTS = {
    # 凌晨 0:00-5:59 权重极低（金融场景几乎无交易）
    0: 1, 1: 1, 2: 1, 3: 1, 4: 1, 5: 1,
    # 早间 6:00-8:59 逐渐升温
    6: 3, 7: 5, 8: 8,
    # 工作时间 9:00-11:59 高峰
    9: 15, 10: 18, 11: 16,
    # 午间 12:00-13:59 略降
    12: 10, 13: 12,
    # 下午 14:00-17:59 高峰
    14: 16, 15: 18, 16: 15, 17: 12,
    # 晚间 18:00-21:59 逐渐下降
    18: 8, 19: 6, 20: 4, 21: 3,
    # 深夜 22:00-23:59
    22: 2, 23: 1,
}


def _weighted_hour_sample(rng, n_samples=1, hour_weights=None):
    # type: (random.Random, int, Optional[Dict[int, int]]) -> List[int]
    """
    根据小时权重采样时间点的小时数

    输入：
      rng: 随机数生成器
      n_samples: 采样数量
      hour_weights: 小时→权重映射（默认使用金融场景权重）
    输出：
      小时数列表，已排序（保证同一任务内时间递增）
    """
    weights = hour_weights or _DEFAULT_HOUR_WEIGHTS
    hours = list(weights.keys())
    w = [weights[h] for h in hours]
    total = sum(w)
    probs = [x / total for x in w]

    sampled = []
    for _ in range(n_samples):
        r = rng.random()
        cumsum = 0.0
        for h, p in zip(hours, probs):
            cumsum += p
            if r <= cumsum:
                sampled.append(h)
                break

    sampled.sort()  # 同一任务内时间必须递增
    return sampled


# ============================================================
# 语义注入 Agent
# ============================================================

class SemanticAgent:
    """
    Phase 3 语义注入 Agent

    职责：
    1. 接收 Task（宏观边 + 上下文），生成 2~5 条微观时序边
    2. 微观边包含：精确时间戳、金额、交易类型、设备、IP 等属性
    3. Mock 模式：纯算法生成（不调 LLM，快速、可离线）
    4. LLM 模式：构建 Prompt → 调用 LLM → 解析 JSON 响应
    5. 记录 agent_trace（Prompt + Response + 验证结果）
    6. 支持用户注入事件的上下文追加

    关键约束：
    - micro_time 必须在所属 macro_time 范围内
    - 同一 Task 的多条微观边时间必须严格递增
    - 时间分布不能均匀，要符合 RAG 时间模式
    - 时间戳格式由 micro_granularity 配置决定
    """

    def __init__(self, rag_rules="", use_mock=None, injected_events=None,
                 hour_weights=None, seed=None, anomaly_rate=0.1):
        # type: (str, Optional[bool], Optional[List[Dict]], Optional[Dict[int,int]], Optional[int], float) -> None
        """
        输入：
          rag_rules: RAG 行业规则文本（由第5批 rag/ 模块提供）
          use_mock: 是否使用 Mock 模式（None 则根据 LLM_BACKEND 判断）
          injected_events: 用户注入的事件列表（追加到 Prompt 上下文）
          hour_weights: 自定义小时权重（Mock 模式时间采样用）
          seed: 随机种子（可复现）
          anomaly_rate: 异常率控制（0.0~1.0），Agent 主动按此比例生成异常边
        """
        if use_mock is not None:
            self._use_mock = use_mock
        else:
            self._use_mock = (LLM_BACKEND.lower() == "mock")

        self.rag_rules = rag_rules
        self.injected_events = injected_events or []
        self._hour_weights = hour_weights
        self._rng = random.Random(seed)
        self._llm = LLMCaller()
        self._anomaly_rate = max(0.0, min(1.0, anomaly_rate))

        # 统计计数器
        self._stats = {
            "tasks_processed": 0,
            "micro_edges_generated": 0,
            "llm_calls": 0,
            "mock_calls": 0,
            "validation_failures": 0,
            "anomaly_edges_generated": 0,
        }

        logger.info("SemanticAgent 初始化: mock=%s, rag_rules=%d chars, anomaly_rate=%.2f",
                     self._use_mock, len(rag_rules), self._anomaly_rate)

    # ============================================================
    # 注入事件管理
    # ============================================================

    def add_injected_event(self, event):
        # type: (Dict[str, Any]) -> None
        """
        添加用户注入的事件

        输入：event 字典，如
          { "scope": "global", "timestamp": "Day_5",
            "description": "央行加息 50 基点，所有贷款利率上调" }
        调用时机：用户在运行中点击"注入事件"后
        """
        self.injected_events.append(event)
        log_event(3, "event_injected",
                  "Agent 收到注入事件: {d}".format(d=event.get("description", "")[:80]))

    # ============================================================
    # 核心处理方法
    # ============================================================

    def process_task(self, task):
        # type: (Dict[str, Any]) -> List[Dict[str, Any]]
        """
        处理单个 Task，生成微观边列表（同步接口）

        输入：
          task: Phase 2 输出的 Task 字典
            {
              task_id, macro_edge_ref, instruction, edge_type, initial_tags,
              context: {
                current_day, block_index, total_blocks, micro_granularity,
                actor, target, actor_balance, target_balance,
                actor_state, target_state, actor_degree, target_degree
              }
            }
        输出：
          微观边列表
            [
              {
                micro_time: "Day_5_14:23",
                source: "N_0001",
                target: "N_0002",
                amount: 3500,
                properties: {
                  transaction_type: "normal_transfer",
                  risk_score: 0.1,
                  ip: "192.168.1.42",
                  device: "mobile_ios",
                  task_ref: "T_00001",
                  macro_edge_ref: "E_00001"
                }
              },
              ...
            ]
        调用时机：Pipeline Phase 3 循环中对每个 Task 调用
        """
        if self._use_mock:
            edges = self._mock_generate(task)
            self._stats["mock_calls"] += 1
        else:
            # LLM 模式需要异步调用，这里包装为同步
            loop = None
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                pass

            if loop and loop.is_running():
                # 已在事件循环中（如 server.py 调用时），创建新任务
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    edges = pool.submit(
                        asyncio.run, self._llm_generate(task)
                    ).result()
            else:
                edges = asyncio.run(self._llm_generate(task))
            self._stats["llm_calls"] += 1

        # --- 验证 ---
        valid_edges = self._validate_micro_edges(edges, task)

        # --- 记录 trace ---
        self._stats["tasks_processed"] += 1
        self._stats["micro_edges_generated"] += len(valid_edges)

        return valid_edges

    async def process_task_async(self, task):
        # type: (Dict[str, Any]) -> List[Dict[str, Any]]
        """
        异步处理单个 Task（LLM 模式下的原生异步接口）

        输入/输出同 process_task
        调用时机：server.py 在 asyncio 事件循环中并发调用多个 Task
        """
        if self._use_mock:
            edges = self._mock_generate(task)
            self._stats["mock_calls"] += 1
        else:
            edges = await self._llm_generate(task)
            self._stats["llm_calls"] += 1

        valid_edges = self._validate_micro_edges(edges, task)
        self._stats["tasks_processed"] += 1
        self._stats["micro_edges_generated"] += len(valid_edges)
        return valid_edges

    async def process_tasks_batch(self, tasks):
        # type: (List[Dict[str, Any]]) -> List[Dict[str, Any]]
        """
        批量处理：
        1. 所有 Task 并发调 LLM 生成正常交易
        2. 代码层面按 anomaly_rate 随机选边标记异常
        3. 对异常边调 LLM 做语义增强（失败则代码扭曲参数）
        """
        semaphore = asyncio.Semaphore(AGENT_CONCURRENCY)
        all_edges = []

        async def _process_one(task):
            async with semaphore:
                return await self.process_task_async(task)

        # 第一步：并发生成所有正常边
        results = await asyncio.gather(
            *[_process_one(t) for t in tasks],
            return_exceptions=True
        )

        for idx, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error("Task %s 处理失败: %s",
                             tasks[idx].get("task_id", "?"), str(result))
                continue
            all_edges.extend(result)

        # 第二步：代码层面标记异常（精确控制）
        total = len(all_edges)
        target_anomaly = int(round(total * self._anomaly_rate))
        if target_anomaly > 0 and total > 0:
            # 随机选 target_anomaly 条标记为异常
            indices = list(range(total))
            self._rng.shuffle(indices)
            anomaly_indices = set(indices[:target_anomaly])

            anomaly_types = [
                "anomaly_structuring", "anomaly_large_amount",
                "anomaly_rapid_movement", "anomaly_unusual_pattern",
                "anomaly_high_frequency", "anomaly_round_trip",
            ]

            for i in anomaly_indices:
                edge = all_edges[i]
                edge["is_anomaly"] = True
                edge["anomaly_type"] = self._rng.choice(anomaly_types)

                # 代码扭曲参数（让异常边的数据确实异常）
                props = edge.get("properties", {})
                atype = edge["anomaly_type"]

                if atype == "anomaly_large_amount":
                    # 金额放大 5-20 倍
                    edge["amount"] = edge.get("amount", 1000) * self._rng.randint(5, 20)
                elif atype == "anomaly_structuring":
                    # 金额刚好卡在阈值下（如 9999）
                    edge["amount"] = self._rng.choice([9999, 9998, 9990, 4999])
                elif atype == "anomaly_rapid_movement":
                    # 金额不变，但会在 Phase 4 看到同节点高频
                    pass
                elif atype == "anomaly_unusual_pattern":
                    # 凌晨交易
                    mt = edge.get("micro_time", "")
                    if "_" in mt:
                        day_part = mt.rsplit("_", 1)[0]
                        h = self._rng.choice([1, 2, 3, 4])
                        m = self._rng.randint(0, 59)
                        edge["micro_time"] = "{d}_{h:02d}:{m:02d}".format(d=day_part, h=h, m=m)
                elif atype == "anomaly_high_frequency":
                    # 金额拆小（典型洗钱拆分）
                    edge["amount"] = self._rng.randint(50, 500)

                # 高 risk_score
                props["risk_score"] = round(self._rng.uniform(0.65, 0.99), 3)
                props["anomaly_reason"] = "Code-marked: " + atype
                edge["properties"] = props
                self._stats["anomaly_edges_generated"] += 1

        logger.info("异常标记完成: %d/%d 条边标记为异常 (目标 %.0f%%)",
                     target_anomaly, total, self._anomaly_rate * 100)

        return all_edges

    # ============================================================
    # Mock 模式生成（纯算法，不调 LLM）
    # ============================================================

    def _mock_generate(self, task):
        # type: (Dict[str, Any]) -> List[Dict[str, Any]]
        """
        Mock 模式：纯算法生成微观边

        生成策略：
        1. 每条宏观边生成 1~4 条微观边（随机）
        2. 金额按对数正态分布生成（模拟真实交易）
        3. 时间戳按小时权重采样（模拟阵发性）
        4. 属性随机但合理（IP / 设备 / 交易类型）

        PERF: 每个 Task 约 0.1ms，10 万 Task 约 10 秒
        """
        ctx = task.get("context", {})
        current_day = ctx.get("current_day", "Day_1")
        actor = ctx.get("actor", "N_0001")
        target = ctx.get("target", "N_0002")
        actor_balance = ctx.get("actor_balance", 10000)
        granularity = ctx.get("micro_granularity", DEFAULT_MICRO_GRANULARITY)
        task_id = task.get("task_id", "T_00000")
        macro_ref = task.get("macro_edge_ref", "E_00000")

        # --- 确定微观边数量 ---
        # 1 条宏观边 = 1 条微观边（边数精确控制）
        n_edges = 1

        # --- 确定余额上限（用于限制单笔金额）---
        if actor_balance == "UNKNOWN":
            # UNKNOWN 余额：Agent 不知道真实余额，使用经验估算
            # 这可能导致超额交易 → Phase 4 标记为 anomaly_overdraft
            # 这是故意设计的"自然涌现异常"机制
            balance_cap = self._rng.randint(5000, 30000)
        else:
            balance_cap = max(100, int(actor_balance))

        # --- 生成时间戳 ---
        timestamps = self._generate_timestamps(
            current_day, n_edges, granularity
        )

        # --- 生成微观边 ---
        edges = []
        remaining = balance_cap

        for i, ts in enumerate(timestamps):
            mu = math.log(max(100, remaining * 0.2))
            sigma = 0.8
            raw_amount = self._rng.lognormvariate(mu, sigma)
            amount = max(10, min(int(raw_amount), remaining))
            remaining = max(0, remaining - amount)

            tx_types = ["normal_transfer", "payment", "deposit", "withdrawal", "fee"]
            tx_weights = [40, 25, 15, 15, 5]
            tx_type = self._rng.choices(tx_types, weights=tx_weights)[0]

            risk_score = round(self._rng.betavariate(2, 10), 3)
            ip = "192.168.{a}.{b}".format(a=self._rng.randint(1, 254), b=self._rng.randint(1, 254))
            device = self._rng.choice(["mobile_ios", "mobile_android", "desktop_chrome", "desktop_firefox", "tablet", "api_client"])

            # 按边级别决定是否异常（每条边独立判断）
            is_anomaly = self._rng.random() < self._anomaly_rate
            anomaly_types = ["anomaly_structuring", "anomaly_large_amount", "anomaly_rapid_movement",
                             "anomaly_unusual_pattern", "anomaly_high_frequency", "anomaly_round_trip"]

            edge = {
                "micro_time": ts,
                "source": actor,
                "target": target,
                "amount": amount,
                "is_anomaly": is_anomaly,
                "anomaly_type": self._rng.choice(anomaly_types) if is_anomaly else "",
                "properties": {
                    "transaction_type": tx_type,
                    "risk_score": round(self._rng.uniform(0.6, 1.0), 3) if is_anomaly else risk_score,
                    "ip": ip,
                    "device": device,
                    "task_ref": task_id,
                    "macro_edge_ref": macro_ref,
                },
            }
            if is_anomaly:
                edge["properties"]["anomaly_reason"] = "Agent-generated: " + edge["anomaly_type"]
                self._stats["anomaly_edges_generated"] += 1

            edges.append(edge)

        return edges

    def _generate_timestamps(self, current_day, n_stamps, granularity):
        # type: (str, int, str) -> List[str]
        """
        生成符合时间模式的微观时间戳列表

        输入：
          current_day: 所属宏观时间块标签（如 "Day_5"）
          n_stamps: 需要生成的时间戳数量
          granularity: 精度 "second" / "minute" / "hour"
        输出：
          时间戳列表，已排序，格式如 "Day_5_14:23"
        调用时机：_mock_generate 和 _parse_llm_response 中

        关键约束：
        - 时间必须在 current_day 范围内（如 Day_5 → 00:00~23:59）
        - 分布不均匀（按小时权重采样）
        - 列表必须严格递增
        """
        # 采样小时数（按权重）
        hours = _weighted_hour_sample(self._rng, n_stamps, self._hour_weights)

        timestamps = []
        for h in hours:
            if granularity == "hour":
                ts = "{day}_{h:02d}".format(day=current_day, h=h)
            elif granularity == "second":
                m = self._rng.randint(0, 59)
                s = self._rng.randint(0, 59)
                ts = "{day}_{h:02d}:{m:02d}:{s:02d}".format(
                    day=current_day, h=h, m=m, s=s)
            else:
                # 默认 minute
                m = self._rng.randint(0, 59)
                ts = "{day}_{h:02d}:{m:02d}".format(
                    day=current_day, h=h, m=m)
            timestamps.append(ts)

        # 确保严格递增（按时间排序）
        timestamps.sort(key=parse_micro_time_key)

        # 去重：如果有重复时间戳，微调分钟/秒使其唯一
        deduped = []
        seen_keys = set()
        for ts in timestamps:
            key = parse_micro_time_key(ts)
            if key in seen_keys:
                # 微调：秒级+1秒，分钟级+1分
                day_part, time_part = ts.rsplit("_", 1) if "_" in ts else (ts, "")
                if ":" in time_part:
                    parts = time_part.split(":")
                    if len(parts) == 3:
                        parts[2] = "{:02d}".format(min(59, int(parts[2]) + 1))
                    elif len(parts) == 2:
                        parts[1] = "{:02d}".format(min(59, int(parts[1]) + 1))
                    time_part = ":".join(parts)
                    ts = "{d}_{t}".format(d=day_part, t=time_part)
                key = parse_micro_time_key(ts)
            seen_keys.add(key)
            deduped.append(ts)

        return deduped

    # ============================================================
    # LLM 模式生成
    # ============================================================

    async def _llm_generate(self, task):
        # type: (Dict[str, Any]) -> List[Dict[str, Any]]
        """
        LLM 模式：构建精简 Prompt → 调用 LLM → 解析 5 参数 JSON
        LLM 只返回 {amount, transaction_type, risk_score, ip, device}
        micro_time / source / target 由代码生成（精确控制时间）
        """
        prompt, system_prompt = self._build_prompt(task)
        response_text = await self._llm.call(prompt, system_prompt)

        ctx = task.get("context", {})
        actor = ctx.get("actor", "N_0001")
        target = ctx.get("target", "N_0002")
        current_day = ctx.get("current_day", "Day_1")
        granularity = ctx.get("micro_granularity", DEFAULT_MICRO_GRANULARITY)
        task_id = task.get("task_id", "")
        macro_ref = task.get("macro_edge_ref", "")

        trace = {
            "task_id": task_id,
            "prompt_sent": prompt[:500] + "..." if len(prompt) > 500 else prompt,
            "llm_response": response_text[:500] + "..." if len(response_text) > 500 else response_text,
            "parsed_edges": [],
            "validation_result": "pending",
        }

        # 解析 LLM 返回的 5 参数 JSON
        amount = None
        tx_type = "transfer"
        risk_score = 0.1
        ip_addr = "192.168.1.{b}".format(b=self._rng.randint(1, 254))
        device = "desktop_chrome"

        if response_text:
            parsed = self._parse_5param_response(response_text)
            if parsed:
                amount = parsed.get("amount")
                tx_type = parsed.get("transaction_type", tx_type)
                risk_score = parsed.get("risk_score", risk_score)
                ip_addr = parsed.get("ip", ip_addr)
                device = parsed.get("device", device)
                trace["validation_result"] = "success"

        # LLM 无响应或解析失败 → 代码生成合理值
        if amount is None:
            balance = ctx.get("actor_balance", 5000)
            if balance == "UNKNOWN":
                balance = self._rng.randint(1000, 10000)
            amount = max(10, int(balance * self._rng.uniform(0.05, 0.3)))
            trace["validation_result"] = "code_generated"

        # 代码生成时间戳（精确控制，不靠 LLM）
        timestamps = self._generate_timestamps(current_day, 1, granularity)
        ts = timestamps[0] if timestamps else "{d}_12:00".format(d=current_day)

        edge = {
            "micro_time": ts,
            "source": actor,
            "target": target,
            "amount": max(1, int(amount)),
            "is_anomaly": False,
            "anomaly_type": "",
            "properties": {
                "transaction_type": tx_type,
                "risk_score": round(float(risk_score), 3) if isinstance(risk_score, (int, float)) else 0.1,
                "ip": ip_addr,
                "device": device,
                "task_ref": task_id,
                "macro_edge_ref": macro_ref,
            },
        }

        trace["parsed_edges"] = [{"time": ts, "amount": edge["amount"]}]
        log_agent_trace(trace)
        return [edge]

    def _parse_5param_response(self, response_text):
        # type: (str) -> Optional[Dict]
        """
        解析 LLM 返回的 5 参数 JSON: {amount, transaction_type, risk_score, ip, device}
        容错处理：去 markdown 包裹，处理数组包裹，提取第一个有效 JSON 对象
        """
        import json

        text = response_text.strip()

        # 去掉 markdown 代码块
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()

        # 尝试直接解析
        try:
            data = json.loads(text)
            if isinstance(data, list) and data:
                data = data[0]
            if isinstance(data, dict) and "amount" in data:
                return data
        except json.JSONDecodeError:
            pass

        # 尝试提取 { } 之间的内容
        import re
        match = re.search(r'\{[^{}]+\}', text)
        if match:
            try:
                data = json.loads(match.group())
                if isinstance(data, dict) and "amount" in data:
                    return data
            except json.JSONDecodeError:
                pass

        return None

    def _build_prompt(self, task):
        # type: (Dict[str, Any]) -> Tuple[str, str]
        """
        构建完整的 LLM Prompt

        输入：task 字典
        输出：(user_prompt, system_prompt) 元组

        Prompt 结构：
        1. 系统角色设定
        2. RAG 行业规则
        3. 当前任务上下文（时间块、节点、余额）
        4. 用户注入事件（如果有）
        5. 输出格式要求（严格 JSON）
        """
        ctx = task.get("context", {})

        system_prompt = (
            "You are a financial transaction data generator. "
            "Respond with valid JSON only. No explanation."
        )

        # --- 构建精简 Prompt（教授方案：qwen 上下文小，只要求 5 个参数）---
        parts = []

        # RAG 规则（精简到关键段落）
        if self.rag_rules:
            parts.append("=== Rules ===")
            # 只取前 800 字符，避免超 context（qwen2.5:3b 上下文有限）
            parts.append(self.rag_rules[:800])
            parts.append("")

        # 任务上下文（精简）
        parts.append("=== Task ===")
        parts.append("Source: {a} (balance={ab}, risk={ar})".format(
            a=ctx.get("actor", "?"),
            ab=ctx.get("actor_balance", "?"),
            ar=ctx.get("actor_state", {}).get("risk_level", "low"),
        ))
        parts.append("Target: {t}".format(t=ctx.get("target", "?")))
        parts.append("Day: {d}".format(d=ctx.get("current_day", "Day_1")))
        parts.append("")

        # 输出格式（只要 5 个参数，时间戳由代码生成）
        balance_hint = ctx.get("actor_balance", 5000)
        if balance_hint == "UNKNOWN":
            balance_hint = "unknown (estimate around 5000)"

        parts.append("Generate 1 realistic transaction for this source node.")
        parts.append("The source has balance={b}. Amount should be reasonable (not too large, not always the same).".format(b=balance_hint))
        parts.append("Return JSON with exactly these 5 fields:")
        parts.append("  amount: positive integer (vary based on balance and context)")
        parts.append("  transaction_type: one of normal_transfer, payment, deposit, withdrawal, fee")
        parts.append("  risk_score: float 0.0-1.0 (low risk for normal transactions)")
        parts.append("  ip: realistic IPv4 address")
        parts.append("  device: one of mobile_ios, mobile_android, desktop_chrome, desktop_firefox, tablet, api_client")
        parts.append("")
        parts.append("Respond ONLY with a single JSON object. No array, no markdown, no explanation.")

        user_prompt = "\n".join(parts)
        return (user_prompt, system_prompt)

    def _parse_llm_response(self, response_text, task):
        # type: (str, Dict[str, Any]) -> List[Dict[str, Any]]
        """
        解析 LLM 的 JSON 响应为微观边列表

        处理策略：
        1. 尝试直接 JSON 解析
        2. 如果失败，尝试提取 JSON 数组部分（去掉 markdown 包裹）
        3. 校验必要字段
        4. 补全缺失的 source/target
        """
        import json

        ctx = task.get("context", {})
        actor = ctx.get("actor", "")
        target = ctx.get("target", "")
        task_id = task.get("task_id", "")
        macro_ref = task.get("macro_edge_ref", "")

        text = response_text.strip()

        # 去掉 markdown 代码块包裹
        if text.startswith("```"):
            # 移除 ```json ... ``` 包裹
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            text = text.strip()

        # 尝试解析 JSON
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # 尝试提取 [...] 部分
            match = re.search(r"\[.*\]", text, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    return []
            else:
                return []

        if not isinstance(data, list):
            data = [data]

        # 校验和补全
        edges = []
        current_day = ctx.get("current_day", "Day_1")
        gran = ctx.get("micro_granularity", "minute")

        for item in data:
            if not isinstance(item, dict):
                continue

            # 补全 source/target
            item.setdefault("source", actor)
            item.setdefault("target", target)

            # 确保 amount 是整数
            try:
                item["amount"] = max(1, int(float(item.get("amount", 100))))
            except (ValueError, TypeError):
                item["amount"] = 100

            # 修正 micro_time：如果缺失或格式不对，自动生成合理值
            mt = item.get("micro_time", "")
            if not mt or not isinstance(mt, str) or not mt.startswith("Day_"):
                # LLM 返回了错误格式（Unix 时间戳、纯数字等）→ 自动生成
                h = self._rng.randint(8, 18)
                m = self._rng.randint(0, 59)
                if gran == "second":
                    s = self._rng.randint(0, 59)
                    mt = "{d}_{h:02d}:{m:02d}:{s:02d}".format(d=current_day, h=h, m=m, s=s)
                elif gran == "hour":
                    mt = "{d}_{h:02d}".format(d=current_day, h=h)
                else:
                    mt = "{d}_{h:02d}:{m:02d}".format(d=current_day, h=h, m=m)
                item["micro_time"] = mt

            # 确保 properties 存在
            props = item.get("properties", {})
            if not isinstance(props, dict):
                props = {}
            props.setdefault("transaction_type", "llm_generated")
            props.setdefault("risk_score", 0.1)
            props["task_ref"] = task_id
            props["macro_edge_ref"] = macro_ref
            item["properties"] = props

            # 处理 LLM 返回的异常标记
            item.setdefault("is_anomaly", False)
            item.setdefault("anomaly_type", "")
            if item["is_anomaly"] and item["anomaly_type"]:
                props["anomaly_reason"] = "LLM-generated: " + str(item["anomaly_type"])
                self._stats["anomaly_edges_generated"] += 1

            edges.append(item)

        return edges

    # ============================================================
    # 验证：微观边合法性检查
    # ============================================================

    def _validate_micro_edges(self, edges, task):
        # type: (List[Dict[str, Any]], Dict[str, Any]) -> List[Dict[str, Any]]
        """
        验证微观边列表的合法性

        检查规则：
        1. micro_time 不为空
        2. micro_time 在所属 macro_time 范围内（前缀匹配）
        3. 同一 Task 的多条边 micro_time 严格递增
        4. amount > 0
        5. source 和 target 不为空

        不合法的边被过滤掉（不中断流水线）

        输入：edges 列表，task 字典
        输出：通过验证的边列表
        """
        ctx = task.get("context", {})
        current_day = ctx.get("current_day", "")
        task_id = task.get("task_id", "")

        valid = []
        prev_key = (0, 0, 0, 0)

        for edge in edges:
            mt = edge.get("micro_time", "")
            amount = edge.get("amount", 0)
            source = edge.get("source", "")
            target = edge.get("target", "")

            # 检查 1: micro_time 非空
            if not mt:
                logger.debug("Task %s: 丢弃空 micro_time 的边", task_id)
                continue

            # 检查 2: micro_time 在 macro_time 范围内
            # 前缀匹配：Day_5_14:23 应以 Day_5 开头
            if current_day and not mt.startswith(current_day):
                logger.debug("Task %s: micro_time %s 不在 %s 范围内",
                             task_id, mt, current_day)
                # 尝试修复：替换前缀
                parts = mt.split("_")
                if len(parts) >= 3:
                    day_parts = current_day.split("_")
                    fixed = current_day + "_" + "_".join(parts[len(day_parts):])
                    edge["micro_time"] = fixed
                    mt = fixed
                else:
                    continue

            # 检查 3: 时间严格递增
            key = parse_micro_time_key(mt)
            if key <= prev_key and valid:
                # 时间不递增：微调使其递增
                d, h, m, s = key
                if s < 59:
                    s += 1
                elif m < 59:
                    m += 1
                    s = 0
                else:
                    h = min(23, h + 1)
                    m = 0
                    s = 0
                # 重建时间戳
                edge["micro_time"] = self._rebuild_timestamp(
                    current_day, h, m, s,
                    ctx.get("micro_granularity", "minute")
                )
                mt = edge["micro_time"]
                key = parse_micro_time_key(mt)

            # 检查 4: amount > 0
            if amount <= 0:
                edge["amount"] = 10  # 最小金额修复

            # 检查 5: source/target 非空
            if not source or not target:
                continue

            prev_key = key
            valid.append(edge)

        if len(valid) < len(edges):
            dropped = len(edges) - len(valid)
            self._stats["validation_failures"] += dropped
            logger.debug("Task %s: 验证丢弃 %d 条，保留 %d 条",
                         task_id, dropped, len(valid))

        return valid

    def _rebuild_timestamp(self, day_label, hour, minute, second, granularity):
        # type: (str, int, int, int, str) -> str
        """根据精度重建时间戳字符串"""
        if granularity == "second":
            return "{d}_{h:02d}:{m:02d}:{s:02d}".format(
                d=day_label, h=hour, m=minute, s=second)
        elif granularity == "hour":
            return "{d}_{h:02d}".format(d=day_label, h=hour)
        else:
            return "{d}_{h:02d}:{m:02d}".format(
                d=day_label, h=hour, m=minute)

    # ============================================================
    # 统计和查询
    # ============================================================

    def get_stats(self):
        # type: () -> Dict[str, Any]
        """
        获取 Agent 运行统计

        输出：
          {
            "tasks_processed": int,
            "micro_edges_generated": int,
            "llm_calls": int,
            "mock_calls": int,
            "validation_failures": int,
            "avg_edges_per_task": float,
            "injected_events_count": int
          }
        调用时机：Phase 3 完成后，用于 injection_complete 消息
        """
        tp = max(self._stats["tasks_processed"], 1)
        return {
            "tasks_processed": self._stats["tasks_processed"],
            "micro_edges_generated": self._stats["micro_edges_generated"],
            "llm_calls": self._stats["llm_calls"],
            "mock_calls": self._stats["mock_calls"],
            "validation_failures": self._stats["validation_failures"],
            "avg_edges_per_task": round(self._stats["micro_edges_generated"] / tp, 2),
            "injected_events_count": len(self.injected_events),
        }
