# ============================================================
# SAGA - Phase 2: 任务调度器（Task Dispatcher）
# 第 3 批 / 共 10 批
# 用途：将 Phase 1 的骨架图按宏观时间块切片，
#       为每条宏观边组装 Agent 任务（Task），
#       严格按时间顺序排列，标记 UNKNOWN 余额
# Pipeline 阶段：Phase 2（按时间块切片 → 组装 Agent 任务）
# ============================================================

from collections import defaultdict, OrderedDict
from typing import Dict, Any, List, Optional, Tuple

from config import (
    DEFAULT_NUM_NODES,
    parse_macro_block_index,
)
from utils.logger import get_logger, log_event

logger = get_logger("saga.core.dispatcher")


# ============================================================
# 默认初始余额分配策略
# 每个节点在 Pipeline 启动时被赋予一个初始余额
# 这里定义的是分配逻辑，不是硬编码值
# ============================================================

def _default_initial_balance(node_id, num_nodes):
    # type: (str, int) -> int
    """
    根据节点 ID 计算默认初始余额

    策略：基于节点序号的哈希式散列，产生 1000~50000 范围内的余额
    这样不同节点有不同起始余额，模拟真实世界的财富分布
    TODO(扩展): 第5批可根据 RAG 场景自定义余额分布
               （如金融场景用对数正态分布，交通场景用均匀分布）
    """
    # 提取节点序号（如 N_0042 → 42）
    try:
        idx = int(node_id.split("_")[-1])
    except (ValueError, IndexError):
        idx = hash(node_id) % 10000

    # 使用简单哈希产生伪随机但确定性的余额
    # 确定性意味着相同 node_id 始终得到相同余额（可复现）
    seed = (idx * 2654435761) % (2 ** 32)  # Knuth 乘法哈希
    balance = 1000 + (seed % 49001)        # 范围 [1000, 50000]
    return balance


class TaskDispatcher:
    """
    Phase 2 任务调度器

    职责：
    1. 将骨架的宏观边按 macro_time 分组
    2. 严格按时间顺序排列各组（Day_1 先于 Day_2）
    3. 为每条宏观边组装 Agent 任务（Task 字典）
    4. 第一个时间块的余额 = initial_balance（已知）
       后续时间块的余额 = "UNKNOWN"（故意设计的信息差）

    关键约束：
    - 任务必须按 macro_time 顺序处理
    - UNKNOWN 余额的信息差是"自然涌现异常"的核心机制
    - 每个 Task 的 context.current_day 必须正确对应其 macro_time
    """

    def __init__(self, num_nodes=None, initial_balance_fn=None):
        # type: (Optional[int], Optional[Any]) -> None
        """
        输入：
          num_nodes: 节点总数（用于初始化余额表）
          initial_balance_fn: 自定义初始余额函数 fn(node_id, num_nodes) -> int
                              TODO(扩展): 第5批可根据 RAG 场景注入不同分配策略
        """
        self.num_nodes = num_nodes if num_nodes is not None else DEFAULT_NUM_NODES
        self._balance_fn = initial_balance_fn or _default_initial_balance
        # 初始余额表：Phase 2 生成时填充，Phase 4 状态机使用
        self.initial_balances = {}  # type: Dict[str, int]

    def dispatch_from_skeleton(self, skeleton, micro_granularity=None):
        # type: (Dict[str, Any], Optional[str]) -> List[Dict[str, Any]]
        """
        从骨架字典生成完整的 Agent 任务列表

        输入：
          skeleton: Phase 1 输出的骨架字典
                    { nodes, macro_edges, metadata, degree_map }
          micro_granularity: 微观时间精度（传递给 Task 上下文，
                             Agent 据此决定时间戳格式）
        输出：
          按时间顺序排列的 Task 列表
          每个 Task 是一个字典（详见 _build_task 方法注释）
        调用时机：Phase 1 骨架生成完成后立即调用

        处理流程：
        1. 为所有节点计算初始余额
        2. 将宏观边按 macro_time 分组
        3. 按时间块顺序遍历，为每条边创建 Task
        4. 第一个时间块任务余额已知，后续标记 UNKNOWN
        """
        nodes = skeleton.get("nodes", [])
        macro_edges = skeleton.get("macro_edges", [])
        metadata = skeleton.get("metadata", {})
        degree_map = skeleton.get("degree_map", {})

        mg = micro_granularity or metadata.get("micro_granularity", "minute")
        num_nodes = len(nodes)

        log_event(2, "dispatch_start",
                  "任务调度开始: {ne} 条宏观边, {nn} 个节点".format(
                      ne=len(macro_edges), nn=num_nodes))

        # --- Step 1: 初始化每个节点的余额 ---
        self.initial_balances = {}
        for node_id in nodes:
            self.initial_balances[node_id] = self._balance_fn(node_id, num_nodes)

        # --- Step 2: 按 macro_time 分组宏观边 ---
        # 使用 OrderedDict 保留插入顺序（按时间排序后的顺序）
        time_groups = defaultdict(list)  # type: Dict[str, List[Dict[str, Any]]]
        for edge in macro_edges:
            mt = edge.get("macro_time", "Block_1")
            time_groups[mt].append(edge)

        # --- Step 3: 按时间顺序排序时间块 ---
        # 从标签中提取序号，按序号排序
        sorted_blocks = sorted(
            time_groups.keys(),
            key=lambda label: parse_macro_block_index(label)
        )

        # --- Step 4: 按时间块顺序生成 Task ---
        tasks = []
        first_block = sorted_blocks[0] if sorted_blocks else None
        task_counter = 0

        for block_idx, block_label in enumerate(sorted_blocks):
            edges_in_block = time_groups[block_label]
            is_first_block = (block_label == first_block)

            for edge in edges_in_block:
                task_counter += 1
                task = self._build_task(
                    edge=edge,
                    block_label=block_label,
                    block_index=block_idx + 1,
                    total_blocks=len(sorted_blocks),
                    is_first_block=is_first_block,
                    degree_map=degree_map,
                    micro_granularity=mg,
                    task_seq=task_counter,
                )
                tasks.append(task)

        # --- 日志 ---
        log_event(2, "dispatch_complete",
                  "任务调度完成: {nt} 个任务, {nb} 个时间块".format(
                      nt=len(tasks), nb=len(sorted_blocks)),
                  {
                      "total_tasks": len(tasks),
                      "total_time_blocks": len(sorted_blocks),
                      "time_blocks": sorted_blocks,
                      "tasks_per_block": {
                          bl: len(time_groups[bl]) for bl in sorted_blocks
                      },
                  })

        return tasks

    def _build_task(
        self,
        edge,             # type: Dict[str, Any]
        block_label,      # type: str
        block_index,      # type: int
        total_blocks,     # type: int
        is_first_block,   # type: bool
        degree_map,       # type: Dict[str, int]
        micro_granularity,  # type: str
        task_seq,         # type: int
    ):
        # type: (...) -> Dict[str, Any]
        """
        为单条宏观边构建 Agent 任务字典

        输入：
          edge: 宏观边字典 { edge_id, source, target, macro_time, type, initial_tags }
          block_label: 所属时间块标签（如 "Day_5"）
          block_index: 时间块序号（从 1 开始）
          total_blocks: 时间块总数
          is_first_block: 是否为第一个时间块
          degree_map: 节点度数映射
          micro_granularity: 微观时间精度
          task_seq: 任务全局序号
        输出：
          Task 字典，包含 Agent 生成微观边所需的全部上下文

        UNKNOWN 余额机制（核心设计！）：
          第一个时间块 → 余额已知 = initial_balance
          后续时间块 → 余额标记为 "UNKNOWN"
          Agent 拿到 UNKNOWN 后可能生成超额交易
          → Phase 4 检测到余额不足 → anomaly_overdraft
          → 这就是"自然涌现"异常的来源
        """
        source = edge["source"]
        target = edge["target"]

        # --- 余额确定逻辑 ---
        if is_first_block:
            # 第一个时间块：余额已知
            actor_balance = self.initial_balances.get(source, 10000)
            target_balance = self.initial_balances.get(target, 10000)
        else:
            # 后续时间块：余额标记为 UNKNOWN
            # 因为真实余额取决于之前所有时间块的结算结果
            # Phase 2 在 Phase 4 之前执行，无法提前知道
            actor_balance = "UNKNOWN"
            target_balance = "UNKNOWN"

        # --- 节点状态上下文 ---
        # Phase 2 只能提供初始状态，真实状态在 Phase 4 动态维护
        actor_state = {
            "risk_level": "low",
            "transaction_count": 0,
            "anomaly_count": 0,
            "status": "active",
        }
        target_state = {
            "risk_level": "low",
            "transaction_count": 0,
            "anomaly_count": 0,
            "status": "active",
        }

        task = {
            "task_id": "T_{seq:05d}".format(seq=task_seq),
            "macro_edge_ref": edge["edge_id"],
            "context": {
                # 时间上下文（Agent 必须在此范围内生成 micro_time）
                "current_day": block_label,
                "block_index": block_index,
                "total_blocks": total_blocks,
                "micro_granularity": micro_granularity,
                # 节点上下文
                "actor": source,
                "target": target,
                "actor_balance": actor_balance,
                "target_balance": target_balance,
                "actor_state": actor_state,
                "target_state": target_state,
                # 图拓扑上下文（Agent 可据此决定交易金额等）
                "actor_degree": degree_map.get(source, 1),
                "target_degree": degree_map.get(target, 1),
            },
            "instruction": "Generate micro-transactions for this macro edge",
            "initial_tags": edge.get("initial_tags", {}),
            "edge_type": edge.get("type", "transfer"),
        }

        return task

    # ============================================================
    # 任务统计（供前端 StatsPanel 使用）
    # ============================================================

    def get_dispatch_stats(self, tasks):
        # type: (List[Dict[str, Any]]) -> Dict[str, Any]
        """
        从任务列表中提取调度统计信息

        输入：tasks 列表
        输出：
          {
            "total_tasks": int,
            "time_blocks": [有序的时间块标签列表],
            "tasks_per_block": { "Day_1": 15, "Day_2": 8, ... },
            "unique_actors": int,
            "unique_targets": int,
            "known_balance_tasks": int,   # 余额已知的任务数
            "unknown_balance_tasks": int, # 余额 UNKNOWN 的任务数
          }
        调用时机：Phase 2 完成后推送给前端
        """
        if not tasks:
            return {
                "total_tasks": 0,
                "time_blocks": [],
                "tasks_per_block": {},
                "unique_actors": 0,
                "unique_targets": 0,
                "known_balance_tasks": 0,
                "unknown_balance_tasks": 0,
            }

        # 按时间块统计
        block_counts = defaultdict(int)  # type: Dict[str, int]
        actors = set()
        targets = set()
        known_count = 0
        unknown_count = 0

        for task in tasks:
            ctx = task.get("context", {})
            bl = ctx.get("current_day", "")
            block_counts[bl] += 1
            actors.add(ctx.get("actor", ""))
            targets.add(ctx.get("target", ""))

            if ctx.get("actor_balance") == "UNKNOWN":
                unknown_count += 1
            else:
                known_count += 1

        # 按时间排序
        sorted_blocks = sorted(
            block_counts.keys(),
            key=lambda label: parse_macro_block_index(label)
        )

        return {
            "total_tasks": len(tasks),
            "time_blocks": sorted_blocks,
            "tasks_per_block": {bl: block_counts[bl] for bl in sorted_blocks},
            "unique_actors": len(actors),
            "unique_targets": len(targets),
            "known_balance_tasks": known_count,
            "unknown_balance_tasks": unknown_count,
        }

    def get_initial_balances(self):
        # type: () -> Dict[str, int]
        """
        获取所有节点的初始余额映射

        输出：{ "N_0001": 35000, "N_0002": 12000, ... }
        调用时机：Phase 4 状态机初始化时需要知道初始余额
        """
        return dict(self.initial_balances)
