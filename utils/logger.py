# ============================================================
# SAGA - 日志系统
# 第 1 批 / 共 10 批
# 用途：提供统一的日志记录能力，覆盖后端所有模块
#       同时维护结构化事件日志列表（用于导出运行日志 JSON）
# Pipeline 阶段：贯穿所有阶段
# ============================================================

import os
import sys
import time
import logging
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional

# orjson 是 C 底层 JSON 库，比标准库快 5-10 倍
# 在高频日志写入场景下（Phase 3/4 每条边都写日志）性能优势明显
try:
    import orjson

    def _json_dumps(obj):
        # type: (Any) -> str
        """使用 orjson 序列化，性能约为标准库 5-10 倍"""
        return orjson.dumps(obj).decode("utf-8")
except ImportError:
    import json

    def _json_dumps(obj):
        # type: (Any) -> str
        """回退到标准库 json"""
        return json.dumps(obj, ensure_ascii=False, default=str)


# ============================================================
# 结构化事件日志（用于导出和前端 EventLog 组件）
# ============================================================

# 全局事件日志列表，线程安全
# 每个事件是一个 dict: { timestamp, phase, event_type, message, data }
# 在 pipeline_complete 时可通过 get_event_log() 导出
_event_log = []        # type: List[Dict[str, Any]]
_event_log_lock = threading.Lock()

# Agent 推理记录列表
# 每次 Agent 调用的详细记录: { task_id, prompt_sent, llm_response, parsed_edges, ... }
_agent_traces = []     # type: List[Dict[str, Any]]
_agent_traces_lock = threading.Lock()


def log_event(phase, event_type, message, data=None):
    # type: (int, str, str, Optional[Dict[str, Any]]) -> Dict[str, Any]
    """
    记录一条结构化事件到全局事件日志

    输入：
      phase: 当前 Pipeline 阶段 (1/2/3/4/0 表示非阶段性事件)
      event_type: 事件类型标识，如 "skeleton_start", "micro_edge_generated",
                  "anomaly_detected", "settlement_complete" 等
      message: 人类可读的事件描述（中英文均可）
      data: 可选的附加数据字典（任意结构）
    输出：
      创建的事件 dict（已加入全局列表）
    调用时机：任何需要记录的事件发生时

    注意：此函数是线程安全的，可在多个 Agent 协程中并发调用
    """
    event = {
        "timestamp": datetime.now().isoformat(),
        "phase": phase,
        "event_type": event_type,
        "message": message,
        "data": data,
    }
    with _event_log_lock:
        _event_log.append(event)

    # 同时用标准 logging 输出到控制台和文件
    logger = get_logger("saga.event")
    logger.info("[Phase %d] [%s] %s", phase, event_type, message)

    return event


def log_agent_trace(trace):
    # type: (Dict[str, Any]) -> None
    """
    记录一条 Agent 推理轨迹

    输入：
      trace: Agent 推理记录字典，应包含：
        { task_id, prompt_sent, llm_response, parsed_edges,
          validation_result, settlement_tag }
    调用时机：Phase 3 每次 Agent 完成一个 Task 后

    注意：trace 数据可能较大（含完整 prompt 和 response），
          生产环境可考虑只保留摘要。
    """
    trace["logged_at"] = datetime.now().isoformat()
    with _agent_traces_lock:
        _agent_traces.append(trace)


def get_event_log():
    # type: () -> List[Dict[str, Any]]
    """
    获取完整事件日志列表的副本

    输出：事件列表的浅拷贝（避免外部修改影响内部状态）
    调用时机：导出运行日志时（GET /download-log）
    """
    with _event_log_lock:
        return list(_event_log)


def get_agent_traces():
    # type: () -> List[Dict[str, Any]]
    """
    获取完整 Agent 推理记录列表的副本

    输出：推理记录列表的浅拷贝
    调用时机：导出运行日志时
    """
    with _agent_traces_lock:
        return list(_agent_traces)


def clear_logs():
    # type: () -> None
    """
    清空所有日志记录

    调用时机：新一轮 Pipeline 启动前，清除上次运行的日志
    """
    with _event_log_lock:
        _event_log.clear()
    with _agent_traces_lock:
        _agent_traces.clear()


def get_event_log_size():
    # type: () -> int
    """获取当前事件日志条数（用于内存监控）"""
    with _event_log_lock:
        return len(_event_log)


# ============================================================
# 标准 Python logging 配置
# ============================================================

# 缓存已创建的 logger 实例，避免重复配置
_loggers = {}  # type: Dict[str, logging.Logger]
_setup_done = False


def _setup_root_logger():
    # type: () -> None
    """
    配置根 logger 的格式和处理器

    只在第一次调用 get_logger() 时执行一次。
    日志同时输出到：
    1. 控制台 (stdout) - 带颜色的简洁格式
    2. 文件 (LOG_FILE) - 带完整时间戳的详细格式
    """
    global _setup_done
    if _setup_done:
        return
    _setup_done = True

    # 从 config 读取日志配置
    # 这里延迟导入避免循环依赖
    from config import LOG_LEVEL, LOG_FILE, OUTPUT_DIR

    # 确保输出目录存在
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    # 确保日志文件的父目录存在
    log_dir = os.path.dirname(LOG_FILE)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    # 解析日志级别
    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)

    # 控制台处理器 - 简洁格式
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_format = logging.Formatter(
        # 格式：[时间] [级别] [模块] 消息
        "[%(asctime)s] [%(levelname)-5s] [%(name)s] %(message)s",
        datefmt="%H:%M:%S"
    )
    console_handler.setFormatter(console_format)

    # 文件处理器 - 详细格式
    try:
        file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)  # 文件记录所有级别
        file_format = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_format)
    except (IOError, OSError):
        # 如果无法创建日志文件（权限等问题），只用控制台
        file_handler = None

    # 配置根 logger
    root = logging.getLogger("saga")
    root.setLevel(logging.DEBUG)  # 根 logger 设为 DEBUG，由 handler 控制过滤
    root.addHandler(console_handler)
    if file_handler:
        root.addHandler(file_handler)

    # 避免日志向上传播到 Python 默认 root logger
    root.propagate = False


def get_logger(name="saga"):
    # type: (str) -> logging.Logger
    """
    获取一个命名的 logger 实例

    输入：
      name: logger 名称，建议用模块路径格式如 "saga.core.skeleton"
    输出：
      配置好的 logging.Logger 实例
    调用时机：每个模块文件顶部调用一次

    使用示例：
      logger = get_logger("saga.core.skeleton")
      logger.info("骨架生成开始: %d 节点, %d 边", num_nodes, num_edges)
      logger.warning("igraph 不可用，回退到 networkx")
      logger.error("时间戳解析失败: %s", timestamp)
    """
    if name not in _loggers:
        _setup_root_logger()
        # 所有 saga.* 的 logger 都是 "saga" 根 logger 的子 logger
        # 自动继承其 handler 和格式
        if not name.startswith("saga"):
            name = "saga." + name
        _loggers[name] = logging.getLogger(name)
    return _loggers[name]


# ============================================================
# 性能计时工具
# ============================================================

class Timer:
    """
    简易计时器，用于测量各阶段耗时

    使用方式 A（上下文管理器）：
      with Timer("Phase 1 骨架生成") as t:
          generate_skeleton()
      print(t.elapsed)  # 秒

    使用方式 B（手动）：
      t = Timer("Phase 4 排序")
      t.start()
      sort_edges()
      t.stop()
      print(t.elapsed)
    """

    def __init__(self, label=""):
        # type: (str) -> None
        self.label = label
        self._start = 0.0  # type: float
        self.elapsed = 0.0  # type: float
        self._logger = get_logger("saga.timer")

    def start(self):
        # type: () -> Timer
        """开始计时"""
        self._start = time.perf_counter()
        return self

    def stop(self):
        # type: () -> float
        """停止计时并返回耗时秒数"""
        self.elapsed = time.perf_counter() - self._start
        if self.label:
            self._logger.info(
                "%s 耗时 %.3f 秒", self.label, self.elapsed
            )
        return self.elapsed

    def __enter__(self):
        # type: () -> Timer
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # type: (Any, Any, Any) -> None
        self.stop()


# ============================================================
# 进度追踪器
# ============================================================

class ProgressTracker:
    """
    进度追踪器，维护当前 Pipeline 的进度状态

    用途：
    - 后端在处理每条边时更新进度
    - 服务器在推送消息时附带 _progress 字段
    - 前端据此更新进度条

    调用时机：
    - Phase 3 每生成一条微观边时 update()
    - Phase 4 每结算一条边时 update()
    - 服务器推送消息时 get_progress()

    线程安全：内部使用锁保护并发更新
    """

    def __init__(self):
        # type: () -> None
        self._lock = threading.Lock()
        self.reset()

    def reset(self):
        # type: () -> None
        """重置进度（新一轮 Pipeline 开始前调用）"""
        with self._lock:
            self.current_phase = 0          # type: int
            self.current_edge_index = 0     # type: int
            self.total_expected_edges = 0   # type: int
            self.current_time_block = ""    # type: str  # 当前处理的宏观时间块标签
            self.total_time_blocks = 0      # type: int
            self.current_block_index = 0    # type: int
            self.phase_start_time = 0.0     # type: float
            self.start_time = 0.0           # type: float

    def set_phase(self, phase, total_expected=None, total_blocks=None):
        # type: (int, Optional[int], Optional[int]) -> None
        """
        设置当前阶段

        输入：
          phase: 阶段号 1/2/3/4
          total_expected: 该阶段预期处理的总边数
          total_blocks: 总时间块数
        """
        with self._lock:
            self.current_phase = phase
            self.phase_start_time = time.perf_counter()
            if self.start_time == 0:
                self.start_time = self.phase_start_time
            if total_expected is not None:
                self.total_expected_edges = total_expected
            if total_blocks is not None:
                self.total_time_blocks = total_blocks

    def update(self, edge_index=None, time_block=None, block_index=None):
        # type: (Optional[int], Optional[str], Optional[int]) -> None
        """
        更新进度

        输入：
          edge_index: 当前处理到第几条边
          time_block: 当前正在处理的宏观时间块标签
          block_index: 当前时间块序号
        """
        with self._lock:
            if edge_index is not None:
                self.current_edge_index = edge_index
            if time_block is not None:
                self.current_time_block = time_block
            if block_index is not None:
                self.current_block_index = block_index

    def get_progress(self):
        # type: () -> Dict[str, Any]
        """
        获取当前进度字典（用于附加到 WebSocket 推送消息中）

        输出：
          {
            current_phase: int,
            current_edge_index: int,
            total_expected_edges: int,
            phase_progress_percent: float,
            overall_progress_percent: float,
            current_time_block: str,
            current_block_index: int,
            total_time_blocks: int,
            elapsed_seconds: float
          }
        """
        with self._lock:
            total = max(self.total_expected_edges, 1)
            phase_pct = (self.current_edge_index / total) * 100.0
            overall_pct = phase_pct  # TODO(扩展): 加权多阶段进度

            now = time.perf_counter()
            elapsed = now - self.start_time if self.start_time > 0 else 0.0

            return {
                "current_phase": self.current_phase,
                "current_edge_index": self.current_edge_index,
                "total_expected_edges": self.total_expected_edges,
                "phase_progress_percent": round(phase_pct, 2),
                "overall_progress_percent": round(overall_pct, 2),
                "current_time_block": self.current_time_block,
                "current_block_index": self.current_block_index,
                "total_time_blocks": self.total_time_blocks,
                "elapsed_seconds": round(elapsed, 2),
            }


# ============================================================
# 全局单例进度追踪器
# 整个 Pipeline 共用一个实例
# ============================================================

progress_tracker = ProgressTracker()
