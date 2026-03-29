# ============================================================
# SAGA - 全局配置模块
# 第 1 批 / 共 10 批
# 用途：从 .env 文件读取所有配置项，提供统一的配置访问接口
#       所有模块通过 config.py 获取配置，不直接读环境变量
# Pipeline 阶段：贯穿所有阶段（Phase 1~4 + 前端 + 服务器）
# ============================================================

import os
import math
from typing import Dict, Any, List, Optional, Tuple

# python-dotenv 从 .env 文件加载环境变量到 os.environ
# 这样项目拷贝到另一台机器只需修改 .env 文件即可运行
from dotenv import load_dotenv

# 加载项目根目录下的 .env 文件
# override=False 表示已有的环境变量不会被 .env 覆盖（方便 Docker 等场景）
load_dotenv(override=False)


# ============================================================
# 辅助函数：类型安全地读取环境变量
# ============================================================

def _env_str(key, default=""):
    # type: (str, str) -> str
    """读取字符串类型的环境变量"""
    return os.getenv(key, default)


def _env_int(key, default=0):
    # type: (str, int) -> int
    """读取整数类型的环境变量，非法值回退到默认值"""
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


def _env_float(key, default=0.0):
    # type: (str, float) -> float
    """读取浮点数类型的环境变量"""
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


def _env_list(key, default=""):
    # type: (str, str) -> List[str]
    """读取逗号分隔的列表类型环境变量，返回字符串列表"""
    raw = os.getenv(key, default)
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


# ============================================================
# 服务器配置
# ============================================================

# WebSocket 服务器绑定地址和端口
# CONFIG: 用户可以在 .env 中修改 SAGA_WS_HOST / SAGA_WS_PORT
WS_HOST = _env_str("SAGA_WS_HOST", "0.0.0.0")
WS_PORT = _env_int("SAGA_WS_PORT", 8765)

# HTTP 服务器绑定地址和端口（用于 /estimate, /download 等 REST 接口）
# CONFIG: 用户可以在 .env 中修改 SAGA_HTTP_HOST / SAGA_HTTP_PORT
HTTP_HOST = _env_str("SAGA_HTTP_HOST", "0.0.0.0")
HTTP_PORT = _env_int("SAGA_HTTP_PORT", 8080)


# ============================================================
# LLM 后端配置
# ============================================================

# LLM 后端选择：ollama / openai / vllm / mock
# CONFIG: 用户可以在 .env 中修改 SAGA_LLM_BACKEND
LLM_BACKEND = _env_str("SAGA_LLM_BACKEND", "mock")

# Ollama 配置
# CONFIG: 用户可以在 .env 中修改 SAGA_OLLAMA_BASE_URL / SAGA_OLLAMA_MODEL
OLLAMA_BASE_URL = _env_str("SAGA_OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = _env_str("SAGA_OLLAMA_MODEL", "qwen2.5:3b")

# OpenAI 兼容接口配置（也适用于 vLLM 等兼容 OpenAI 格式的后端）
# CONFIG: 用户可以在 .env 中修改 SAGA_OPENAI_* 系列变量
OPENAI_BASE_URL = _env_str("SAGA_OPENAI_BASE_URL", "http://localhost:8000/v1")
OPENAI_API_KEY = _env_str("SAGA_OPENAI_API_KEY", "EMPTY")
OPENAI_MODEL = _env_str("SAGA_OPENAI_MODEL", "qwen2.5:3b")

# LLM 调用通用参数
# CONFIG: 用户可以在 .env 中修改这些参数以调优 LLM 行为
LLM_TEMPERATURE = _env_float("SAGA_LLM_TEMPERATURE", 0.7)
LLM_MAX_RETRIES = _env_int("SAGA_LLM_MAX_RETRIES", 3)
LLM_TIMEOUT_SECONDS = _env_int("SAGA_LLM_TIMEOUT_SECONDS", 30)

# Agent 并发控制
# CONFIG: SAGA_AGENT_CONCURRENCY 控制同时向 LLM 发送的请求数
#         Quadro RTX 6000 (23GB) 建议 50-100
AGENT_CONCURRENCY = _env_int("SAGA_AGENT_CONCURRENCY", 50)
AGENT_BATCH_SIZE = _env_int("SAGA_AGENT_BATCH_SIZE", 10)


# ============================================================
# 图生成默认参数（Phase 1 骨架生成用）
# ============================================================

# CONFIG: 用户可在前端 ConfigPanel 中覆盖这些默认值
DEFAULT_NUM_NODES = _env_int("SAGA_DEFAULT_NUM_NODES", 1000)
DEFAULT_NUM_EDGES = _env_int("SAGA_DEFAULT_NUM_EDGES", 5000)

# 幂律指数 γ：控制度分布的长尾程度
# 2.0~2.5 接近真实社交网络，3.0+ 更均匀
# CONFIG: 用户可以在前端通过滑块调节
DEFAULT_GAMMA = _env_float("SAGA_DEFAULT_GAMMA", 2.5)

# 超级节点比例：控制 hub 节点（高度节点）占总节点的比例
# CONFIG: 用户可以在前端通过滑块调节
DEFAULT_HUB_RATIO = _env_float("SAGA_DEFAULT_HUB_RATIO", 0.05)


# ============================================================
# 时间维度配置（最重要的横切关注点）
#
# SAGA 生成的是时序图（Temporal Graph），时间是第一等公民。
# 时间配置三层结构：
#   时间跨度（最大）> 宏观时间块粒度（中间）> 微观时间戳精度（最小）
# ============================================================

# --- 时间跨度（Time Span）---
# 含义：生成的时序图覆盖多长时间
# CONFIG: 用户在前端输入数值 + 选择单位
DEFAULT_TIME_SPAN_VALUE = _env_int("SAGA_DEFAULT_TIME_SPAN_VALUE", 30)
# 单位选项：hour / day / week / month / year
DEFAULT_TIME_SPAN_UNIT = _env_str("SAGA_DEFAULT_TIME_SPAN_UNIT", "day")

# --- 宏观时间块粒度（Macro Time Block Size）---
# 含义：Phase 1 骨架中 macro_time 字段的时间单位
#        Phase 2 按这个粒度切分任务
# 选项：hour / day / week / month
# 约束：宏观粒度 ≤ 时间跨度
# CONFIG: 用户在前端下拉选择
DEFAULT_MACRO_BLOCK_UNIT = _env_str("SAGA_DEFAULT_MACRO_BLOCK_UNIT", "day")

# --- 微观时间精度（Micro Time Granularity）---
# 含义：Phase 3 Agent 生成的 micro_time 时间戳的最小精度
# 选项：second / minute / hour
# 约束：微观精度 ≤ 宏观粒度
# CONFIG: 用户在前端下拉选择
DEFAULT_MICRO_GRANULARITY = _env_str("SAGA_DEFAULT_MICRO_GRANULARITY", "minute")

# 各时间单位换算为天数的映射表
# 用于 get_time_span_days() 计算
_TIME_UNIT_TO_DAYS = {
    "hour": 1.0 / 24.0,
    "day": 1.0,
    "week": 7.0,
    "month": 30.0,
    "year": 365.0,
}

# 宏观时间块单位换算为天数
_MACRO_BLOCK_TO_DAYS = {
    "hour": 1.0 / 24.0,
    "day": 1.0,
    "week": 7.0,
    "month": 30.0,
}

# 微观时间戳格式模板
# 由 MICRO_GRANULARITY 自动决定，用户无需手动配置
_TIMESTAMP_FORMATS = {
    "second": "Day_{day}_{hour:02d}:{minute:02d}:{second:02d}",
    "minute": "Day_{day}_{hour:02d}:{minute:02d}",
    "hour": "Day_{day}_{hour:02d}",
}

# 宏观时间块标签前缀映射
# 按小时切 → "Hour_0", "Hour_1", ...
# 按天切 → "Day_1", "Day_2", ...
_MACRO_BLOCK_PREFIX = {
    "hour": "Hour",
    "day": "Day",
    "week": "Week",
    "month": "Month",
}


# ============================================================
# 时间维度辅助函数
# 这些函数被 Phase 1~4 和服务器共同使用
# ============================================================

def get_time_span_days(span_value=None, span_unit=None):
    # type: (Optional[int], Optional[str]) -> int
    """
    将用户输入的时间跨度统一换算为天数

    输入：
      span_value: 数值（默认使用 DEFAULT_TIME_SPAN_VALUE）
      span_unit: 单位（默认使用 DEFAULT_TIME_SPAN_UNIT）
    输出：
      整数天数（至少为 1）
    调用时机：Phase 1 生成骨架前、Phase 2 切片前、前端预估计算
    """
    val = span_value if span_value is not None else DEFAULT_TIME_SPAN_VALUE
    unit = span_unit if span_unit is not None else DEFAULT_TIME_SPAN_UNIT
    multiplier = _TIME_UNIT_TO_DAYS.get(unit, 1.0)
    return max(1, int(math.ceil(val * multiplier)))


def get_total_macro_blocks(span_value=None, span_unit=None, block_unit=None):
    # type: (Optional[int], Optional[str], Optional[str]) -> int
    """
    计算总宏观时间块数

    输入：
      span_value, span_unit: 时间跨度（默认使用全局配置）
      block_unit: 宏观粒度单位（默认使用全局配置）
    输出：
      时间块总数（至少为 1）
    调用时机：Phase 1 分配 macro_time、Phase 2 分组任务、前端进度显示

    示例：跨度 365 天 + 按天切 = 365 块
          跨度 30 天 + 按小时切 = 720 块
    """
    span_days = get_time_span_days(span_value, span_unit)
    bu = block_unit if block_unit is not None else DEFAULT_MACRO_BLOCK_UNIT
    block_days = _MACRO_BLOCK_TO_DAYS.get(bu, 1.0)
    # 向上取整确保覆盖完整跨度
    return max(1, int(math.ceil(span_days / block_days)))


def get_timestamp_format(granularity=None):
    # type: (Optional[str]) -> str
    """
    根据微观精度返回时间戳格式字符串

    输入：
      granularity: 精度选项（默认使用全局配置）
    输出：
      Python format string，包含 {day}, {hour}, {minute}, {second} 占位符
    调用时机：Phase 3 Agent 生成 micro_time 时

    示例：
      "second" → "Day_{day}_{hour:02d}:{minute:02d}:{second:02d}"
      "minute" → "Day_{day}_{hour:02d}:{minute:02d}"
      "hour"   → "Day_{day}_{hour:02d}"
    """
    g = granularity if granularity is not None else DEFAULT_MICRO_GRANULARITY
    return _TIMESTAMP_FORMATS.get(g, _TIMESTAMP_FORMATS["minute"])


def get_macro_block_label(block_index, block_unit=None):
    # type: (int, Optional[str]) -> str
    """
    根据时间块索引和粒度单位生成宏观时间块标签

    输入：
      block_index: 时间块序号（从 1 开始）
      block_unit: 宏观粒度单位
    输出：
      标签字符串，如 "Day_1", "Hour_12", "Week_3", "Month_6"
    调用时机：Phase 1 为每条宏观边分配 macro_time

    注意：block_index 从 1 开始（不是 0），因为 "Day_0" 不符合用户直觉
    """
    bu = block_unit if block_unit is not None else DEFAULT_MACRO_BLOCK_UNIT
    prefix = _MACRO_BLOCK_PREFIX.get(bu, "Block")
    return "{prefix}_{index}".format(prefix=prefix, index=block_index)


def parse_macro_block_index(label):
    # type: (str) -> int
    """
    从宏观时间块标签中提取序号

    输入：
      label: 如 "Day_5", "Hour_12", "Week_3"
    输出：
      整数序号（如 5, 12, 3）
    调用时机：Phase 2 按时间排序任务、Phase 4 跨时间块状态继承
    """
    # 取最后一个下划线后面的数字部分
    parts = label.rsplit("_", 1)
    if len(parts) == 2:
        try:
            return int(parts[1])
        except ValueError:
            pass
    return 0


def parse_micro_time_key(micro_time):
    # type: (str) -> Tuple[int, int, int, int]
    """
    将微观时间戳解析为可排序的元组

    输入：
      micro_time: 如 "Day_5_14:23:07", "Day_5_14:23", "Day_5_14"
    输出：
      (day, hour, minute, second) 元组，缺失的维度补 0
    调用时机：Phase 4 全局排序时作为 sorted() 的 key 函数

    这是 SAGA 中最关键的排序函数之一！
    时序图的正确性完全依赖于这个排序的正确性。
    如果排序错了，余额校验就错了，异常标签就不对了。
    """
    # 分离 "Day_N" 和时间部分
    # "Day_5_14:23:07" → ["Day", "5", "14:23:07"]
    # "Day_5_14:23"    → ["Day", "5", "14:23"]
    # "Day_5_14"       → ["Day", "5", "14"]
    parts = micro_time.split("_")

    day = 0
    hour = 0
    minute = 0
    second = 0

    # 提取天数
    if len(parts) >= 2:
        try:
            day = int(parts[1])
        except ValueError:
            pass

    # 提取时间部分（如果存在）
    if len(parts) >= 3:
        time_str = parts[2]
        time_parts = time_str.split(":")
        if len(time_parts) >= 1:
            try:
                hour = int(time_parts[0])
            except ValueError:
                pass
        if len(time_parts) >= 2:
            try:
                minute = int(time_parts[1])
            except ValueError:
                pass
        if len(time_parts) >= 3:
            try:
                second = int(time_parts[2])
            except ValueError:
                pass

    return (day, hour, minute, second)


def micro_time_to_sortable_int(micro_time):
    # type: (str) -> int
    """
    将微观时间戳转换为单个整数，用于 numpy argsort 加速排序

    输入：
      micro_time: 如 "Day_5_14:23:07"
    输出：
      整数，格式为 DDDDHHMMSS（天数 × 1000000 + 时 × 10000 + 分 × 100 + 秒）
    调用时机：Phase 4 大规模排序时（> 500 万边使用 numpy）

    PERF: 整数比较比元组比较快约 3 倍，适合大规模排序
    """
    day, hour, minute, second = parse_micro_time_key(micro_time)
    return day * 1000000 + hour * 10000 + minute * 100 + second


# ============================================================
# 输出配置
# ============================================================

# 输出目录路径
# CONFIG: 用户可以在 .env 中修改 SAGA_OUTPUT_DIR
OUTPUT_DIR = _env_str("SAGA_OUTPUT_DIR", "./output")

# 默认输出格式列表
# CONFIG: 用户可以在前端勾选需要的输出格式
DEFAULT_OUTPUT_FORMATS = _env_list("SAGA_DEFAULT_OUTPUT_FORMATS", "json,csv")

# 日志级别和文件
# CONFIG: 用户可以在 .env 中修改日志级别
LOG_LEVEL = _env_str("SAGA_LOG_LEVEL", "INFO")
LOG_FILE = _env_str("SAGA_LOG_FILE", "./output/saga.log")


# ============================================================
# 预估基准值配置（用于 POST /estimate 接口）
# ============================================================

# CONFIG: 以下值需要实测后校准
ESTIMATE_CONFIG = {
    # Mock 模式每秒可处理的边数（纯 CPU，不调 LLM）
    "mock_speed_edges_per_sec": _env_int("SAGA_MOCK_SPEED_EDGES_PER_SEC", 5000),
    # LLM 模式每秒可处理的边数（含 GPU 推理开销）
    "llm_speed_edges_per_sec": _env_int("SAGA_LLM_SPEED_EDGES_PER_SEC", 100),
    # 各输出格式下每条边的平均字节数
    "avg_edge_bytes": {
        "json": _env_int("SAGA_AVG_EDGE_BYTES_JSON", 200),
        "csv": _env_int("SAGA_AVG_EDGE_BYTES_CSV", 80),
        "graphml": _env_int("SAGA_AVG_EDGE_BYTES_GRAPHML", 300),
        "edgelist": 30,   # 固定值，格式简单
        "adjlist": 50,    # 固定值，格式简单
    },
}


# ============================================================
# 支持的场景列表
# 前端 ScenarioSelector 读取此列表渲染选项
# ============================================================

# 四大预置行业场景 + 自定义
SUPPORTED_SCENARIOS = [
    {
        "id": "finance_aml",
        "name": "Financial AML",
        "description": "Anti-money laundering transaction graph with FATF typologies",
        "icon": "AccountBalance",  # @mui/icons-material 图标名
        "rag_module": "rag.finance_rules",
    },
    {
        "id": "network_ids",
        "name": "Network IDS",
        "description": "Intrusion detection network traffic graph",
        "icon": "Router",
        "rag_module": "rag.network_rules",
    },
    {
        "id": "cyber_apt",
        "name": "Cyber APT",
        "description": "Advanced persistent threat attack chain graph",
        "icon": "Security",
        "rag_module": "rag.cyber_rules",
    },
    {
        "id": "traffic",
        "name": "Traffic",
        "description": "Urban transportation flow temporal graph",
        "icon": "DirectionsCar",
        "rag_module": "rag.traffic_rules",
    },
    {
        "id": "custom",
        "name": "Custom",
        "description": "User-defined scenario with custom RAG rules",
        "icon": "Tune",
        "rag_module": None,  # 用户自行提供规则文本
    },
]


# ============================================================
# Pipeline 状态枚举
# 后端和前端共用这套状态值
# ============================================================

PIPELINE_STATES = {
    "idle": "idle",           # 等待用户启动
    "running": "running",     # 流水线运行中
    "paused": "paused",       # 用户暂停
    "stopped": "stopped",     # 用户终止（保留已生成数据）
    "completed": "completed", # 流水线正常完成
    "error": "error",         # 出错
}


# ============================================================
# 汇总函数：获取完整配置字典
# 用于序列化传给前端、写入日志、导出时记录
# ============================================================

def get_full_config(overrides=None):
    # type: (Optional[Dict[str, Any]]) -> Dict[str, Any]
    """
    获取当前完整配置的字典形式

    输入：
      overrides: 可选的覆盖字典（前端用户修改的配置项）
                 会合并到默认配置上
    输出：
      包含所有配置项的字典
    调用时机：
      - 前端请求当前配置时
      - 流水线启动前记录配置快照
      - 导出日志时附带配置信息

    注意：该字典中不包含 API Key 等敏感信息
    """
    config = {
        # 服务器
        "ws_host": WS_HOST,
        "ws_port": WS_PORT,
        "http_host": HTTP_HOST,
        "http_port": HTTP_PORT,
        # LLM
        "llm_backend": LLM_BACKEND,
        "llm_temperature": LLM_TEMPERATURE,
        "llm_max_retries": LLM_MAX_RETRIES,
        "llm_timeout_seconds": LLM_TIMEOUT_SECONDS,
        "agent_concurrency": AGENT_CONCURRENCY,
        "agent_batch_size": AGENT_BATCH_SIZE,
        # 图参数
        "num_nodes": DEFAULT_NUM_NODES,
        "num_edges": DEFAULT_NUM_EDGES,
        "gamma": DEFAULT_GAMMA,
        "hub_ratio": DEFAULT_HUB_RATIO,
        # 时间维度（最重要！）
        "time_span_value": DEFAULT_TIME_SPAN_VALUE,
        "time_span_unit": DEFAULT_TIME_SPAN_UNIT,
        "macro_block_unit": DEFAULT_MACRO_BLOCK_UNIT,
        "micro_granularity": DEFAULT_MICRO_GRANULARITY,
        # 计算值
        "time_span_days": get_time_span_days(),
        "total_macro_blocks": get_total_macro_blocks(),
        "timestamp_format": get_timestamp_format(),
        # 输出
        "output_dir": OUTPUT_DIR,
        "output_formats": DEFAULT_OUTPUT_FORMATS,
        # 预估
        "estimate_config": ESTIMATE_CONFIG,
        # 场景
        "supported_scenarios": SUPPORTED_SCENARIOS,
    }

    # 合并用户覆盖配置
    if overrides:
        config.update(overrides)
        # 如果用户覆盖了时间参数，重新计算派生值
        if any(k in overrides for k in [
            "time_span_value", "time_span_unit",
            "macro_block_unit", "micro_granularity"
        ]):
            sv = config.get("time_span_value", DEFAULT_TIME_SPAN_VALUE)
            su = config.get("time_span_unit", DEFAULT_TIME_SPAN_UNIT)
            bu = config.get("macro_block_unit", DEFAULT_MACRO_BLOCK_UNIT)
            mg = config.get("micro_granularity", DEFAULT_MICRO_GRANULARITY)
            config["time_span_days"] = get_time_span_days(sv, su)
            config["total_macro_blocks"] = get_total_macro_blocks(sv, su, bu)
            config["timestamp_format"] = get_timestamp_format(mg)

    return config


def validate_time_config(span_value, span_unit, block_unit, micro_granularity):
    # type: (int, str, str, str) -> Tuple[bool, str]
    """
    校验用户的时间配置是否合法

    输入：
      span_value: 时间跨度数值
      span_unit: 时间跨度单位
      block_unit: 宏观粒度单位
      micro_granularity: 微观精度
    输出：
      (is_valid, error_message) 元组
    调用时机：用户点击"开始生成"之前

    校验规则：
    1. 时间跨度必须 > 0
    2. 各单位必须在允许范围内
    3. 宏观粒度 ≤ 时间跨度（不能跨度 1 天但按月切）
    4. 微观精度 ≤ 宏观粒度（不能宏观按小时但微观按天）
    5. 时间块总数必须在合理范围内（1 ~ 100000）
    """
    # 检查数值
    if span_value <= 0:
        return (False, "Time span value must be positive")

    # 检查单位合法性
    if span_unit not in _TIME_UNIT_TO_DAYS:
        return (False, "Invalid time span unit: {u}. Choose from: {opts}".format(
            u=span_unit, opts=", ".join(_TIME_UNIT_TO_DAYS.keys())
        ))
    if block_unit not in _MACRO_BLOCK_TO_DAYS:
        return (False, "Invalid macro block unit: {u}. Choose from: {opts}".format(
            u=block_unit, opts=", ".join(_MACRO_BLOCK_TO_DAYS.keys())
        ))
    if micro_granularity not in _TIMESTAMP_FORMATS:
        return (False, "Invalid micro granularity: {g}. Choose from: {opts}".format(
            g=micro_granularity, opts=", ".join(_TIMESTAMP_FORMATS.keys())
        ))

    # 检查层级关系：宏观粒度不能大于时间跨度
    span_days = get_time_span_days(span_value, span_unit)
    block_days = _MACRO_BLOCK_TO_DAYS[block_unit]
    if block_days > span_days:
        return (False, "Macro block unit ({bu}) is larger than time span ({sv} {su})".format(
            bu=block_unit, sv=span_value, su=span_unit
        ))

    # 检查层级关系：微观精度不能大于宏观粒度
    # 精度从大到小排序
    granularity_order = {"hour": 3, "minute": 2, "second": 1}
    block_granularity = {"hour": 3, "day": 4, "week": 5, "month": 6}
    micro_level = granularity_order.get(micro_granularity, 2)
    block_level = block_granularity.get(block_unit, 4)
    if micro_level > block_level:
        return (False, "Micro granularity ({mg}) is coarser than macro block unit ({bu})".format(
            mg=micro_granularity, bu=block_unit
        ))

    # 检查时间块总数是否在合理范围
    total_blocks = get_total_macro_blocks(span_value, span_unit, block_unit)
    if total_blocks > 100000:
        return (False, "Too many macro blocks ({n}). Reduce time span or increase block size".format(
            n=total_blocks
        ))

    return (True, "")


# ============================================================
# 预估计算函数（供 POST /estimate 接口使用）
# ============================================================

def estimate_generation(num_nodes, num_edges, mode, formats):
    # type: (int, int, str, List[str]) -> Dict[str, Any]
    """
    预估生成时间、文件大小、GPU 占用

    输入：
      num_nodes: 节点数
      num_edges: 边数
      mode: "mock" 或 "llm"
      formats: 输出格式列表 ["json", "csv", ...]
    输出：
      { estimated_time_seconds, estimated_file_size_mb, gpu_usage_percent }
    调用时机：用户在前端修改配置后实时预估
    """
    ec = ESTIMATE_CONFIG

    # 预估时间
    if mode == "mock":
        speed = ec["mock_speed_edges_per_sec"]
        gpu = 0
    else:
        speed = ec["llm_speed_edges_per_sec"]
        gpu = 75  # LLM 模式下 GPU 占用约 60-90%，取中间值

    estimated_seconds = num_edges / max(speed, 1)

    # 预估文件大小（所有选中格式的总和）
    total_bytes = 0
    for fmt in formats:
        avg_bytes = ec["avg_edge_bytes"].get(fmt, 200)
        total_bytes += num_edges * avg_bytes
    estimated_mb = total_bytes / (1024 * 1024)

    return {
        "estimated_time_seconds": round(estimated_seconds, 1),
        "estimated_file_size_mb": round(estimated_mb, 2),
        "gpu_usage_percent": gpu,
    }
