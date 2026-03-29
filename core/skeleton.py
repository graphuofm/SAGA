# ============================================================
# SAGA - Phase 1: 骨架生成器（Skeleton Generator）
# 第 2 批 / 共 10 批
# 用途：使用 igraph (C 底层) 高速生成幂律分布的有向骨架图，
#       为每条宏观边分配 macro_time 时间块标签，
#       输出标准 skeleton 字典供 Phase 2 切片使用
# Pipeline 阶段：Phase 1（骨架先置）
# ============================================================

import math
import random
from collections import Counter, defaultdict
from typing import Dict, Any, List, Optional, Tuple

import numpy as np

from config import (
    DEFAULT_NUM_NODES, DEFAULT_NUM_EDGES, DEFAULT_GAMMA, DEFAULT_HUB_RATIO,
    DEFAULT_TIME_SPAN_VALUE, DEFAULT_TIME_SPAN_UNIT,
    DEFAULT_MACRO_BLOCK_UNIT, DEFAULT_MICRO_GRANULARITY,
    get_time_span_days, get_total_macro_blocks,
    get_macro_block_label, get_timestamp_format,
)
from utils.logger import get_logger, log_event, Timer

logger = get_logger("saga.core.skeleton")


# ============================================================
# 图引擎选择：优先 igraph (C 底层)，回退 networkx (纯 Python)
# PERF: igraph 百万节点 BA 图 <3 秒，networkx 需要 60-120 秒
# ============================================================

try:
    import igraph as ig
    _ENGINE = "igraph"
    logger.info("图引擎: igraph (C 底层，高性能)")
except ImportError:
    ig = None
    try:
        import networkx as nx
        _ENGINE = "networkx"
        logger.warning("igraph 不可用，回退到 networkx（性能较低）")
    except ImportError:
        nx = None
        _ENGINE = "none"
        logger.error("igraph 和 networkx 均不可用！请安装: pip install python-igraph")


class SkeletonGenerator:
    """
    Phase 1 骨架图生成器

    职责：
    1. 使用 Barabási-Albert 模型生成幂律分布的有向图骨架
    2. 为每条宏观边分配 macro_time 时间块标签（时间是第一等公民！）
    3. 输出标准 skeleton 字典，包含 nodes / macro_edges / metadata / degree_map
    4. 提供度分布预览（纯数学计算，不生成图）

    关键约束：
    - 每条宏观边必须有 macro_time 字段
    - 时间分配不能均匀！要有阵发性（burstiness）
    - degree_map 用于前端节点大小缩放
    """

    def __init__(self):
        # type: () -> None
        self.engine = _ENGINE
        # 随机数生成器（可指定种子保证可复现）
        self._rng = random.Random()

    def set_seed(self, seed):
        # type: (int) -> None
        """
        设置随机种子，使生成结果可复现

        输入：seed 整数种子
        调用时机：需要可复现结果时（如测试、论文数据）
        """
        self._rng = random.Random(seed)
        np.random.seed(seed)

    # ============================================================
    # 核心生成方法
    # ============================================================

    def generate_power_law_skeleton(
        self,
        num_nodes=None,       # type: Optional[int]
        num_edges=None,       # type: Optional[int]
        gamma=None,           # type: Optional[float]
        hub_ratio=None,       # type: Optional[float]
        time_blocks=None,     # type: Optional[int]
        time_span_value=None, # type: Optional[int]
        time_span_unit=None,  # type: Optional[str]
        macro_block_unit=None,  # type: Optional[str]
        micro_granularity=None, # type: Optional[str]
        burstiness=0.3,       # type: float
    ):
        # type: (...) -> Dict[str, Any]
        """
        生成幂律分布的有向骨架图

        输入：
          num_nodes: 节点数（默认从 config 读取）
          num_edges: 期望边数（会被 BA 模型的 m 参数近似）
          gamma: 幂律指数（控制度分布长尾，2.0~3.5）
          hub_ratio: 超级节点比例（预留，影响后续的 hub 标记）
          time_blocks: 直接指定时间块数（优先级高于 time_span 计算）
          time_span_value / time_span_unit: 时间跨度
          macro_block_unit: 宏观时间块粒度
          micro_granularity: 微观时间精度
          burstiness: 阵发性指数 0.0=完全均匀 1.0=极度集中
                      CONFIG: 可由 LLM 推断参数或用户手动设置

        输出：
          skeleton 字典，包含：
          {
            "nodes": ["N_0001", "N_0002", ...],
            "macro_edges": [
              { "edge_id": "E_00001", "source": "N_0001", "target": "N_0002",
                "macro_time": "Day_1", "type": "transfer", "initial_tags": {} },
              ...
            ],
            "metadata": {
              "total_nodes": int,
              "total_edges": int,
              "time_span": "Day_1 to Day_30",
              "total_time_blocks": int,
              "macro_block_unit": str,
              "micro_granularity": str,
              "edges_per_block_avg": float,
              "generator_type": "igraph_barabasi_albert",
              "gamma": float,
              "hub_ratio": float,
              "burstiness": float
            },
            "degree_map": { "N_0001": 15, "N_0002": 3, ... }
          }

        调用时机：用户点击"开始生成"后，Pipeline 第一步执行
        """
        # --- 参数处理：使用传入值或回退到 config 默认值 ---
        n = num_nodes if num_nodes is not None else DEFAULT_NUM_NODES
        target_edges = num_edges if num_edges is not None else DEFAULT_NUM_EDGES
        g = gamma if gamma is not None else DEFAULT_GAMMA
        hr = hub_ratio if hub_ratio is not None else DEFAULT_HUB_RATIO

        # 时间参数
        mbu = macro_block_unit if macro_block_unit is not None else DEFAULT_MACRO_BLOCK_UNIT
        mg = micro_granularity if micro_granularity is not None else DEFAULT_MICRO_GRANULARITY
        tsv = time_span_value if time_span_value is not None else DEFAULT_TIME_SPAN_VALUE
        tsu = time_span_unit if time_span_unit is not None else DEFAULT_TIME_SPAN_UNIT

        # 计算时间块数：优先使用直接指定的 time_blocks
        if time_blocks is not None:
            total_blocks = max(1, time_blocks)
        else:
            total_blocks = get_total_macro_blocks(tsv, tsu, mbu)

        log_event(1, "skeleton_start",
                  "骨架生成开始: {n} 节点, ~{e} 边, γ={g}, {tb} 时间块".format(
                      n=n, e=target_edges, g=g, tb=total_blocks))

        with Timer("Phase 1 骨架生成") as timer:
            # --- Step 1: 使用 igraph/networkx 生成 BA 图 ---
            # 修复 #5: BA 模型的 m 参数必须精确计算
            # BA 模型实际边数 ≈ m * (n - m)，所以要生成 >= target_edges 条边再裁剪
            # 骨架边数 = 用户要求的总边数（1 条宏观边 → 1 条微观边）
            overshoot_target = int(target_edges * 1.05) + 100  # 多生成 5% + 100 保证够裁剪
            raw_edges = self._generate_ba_graph(n, overshoot_target, g)
            
            # 精确裁剪到 target_edges（随机采样保持度分布特征）
            if len(raw_edges) > target_edges:
                indices = list(range(len(raw_edges)))
                self._rng.shuffle(indices)
                keep = sorted(indices[:target_edges])
                raw_edges = [raw_edges[i] for i in keep]
                logger.info("裁剪边数: %d → %d (精确目标 %d)", 
                           len(indices), len(raw_edges), target_edges)
            elif len(raw_edges) < target_edges:
                # BA 生成不够时，补充随机边直到达标
                logger.warning("BA 生成 %d 条边 < 目标 %d，补充随机边", len(raw_edges), target_edges)
                existing_set = set(raw_edges)
                while len(raw_edges) < target_edges:
                    src = self._rng.randint(0, n - 1)
                    tgt = self._rng.randint(0, n - 1)
                    if src != tgt and (src, tgt) not in existing_set:
                        raw_edges.append((src, tgt))
                        existing_set.add((src, tgt))
            
            actual_edge_count = len(raw_edges)

            # --- Step 2: 生成节点 ID 列表 ---
            node_ids = self._generate_node_ids(n)

            # --- Step 3: 为每条边分配 macro_time（时间是第一等公民！）---
            time_assignments = self._assign_macro_times(
                actual_edge_count, total_blocks, mbu, burstiness
            )

            # --- Step 4: 组装 macro_edges 列表 ---
            macro_edges = []
            for idx, (src_idx, tgt_idx) in enumerate(raw_edges):
                edge_id = "E_{eid:05d}".format(eid=idx + 1)
                macro_edges.append({
                    "edge_id": edge_id,
                    "source": node_ids[src_idx],
                    "target": node_ids[tgt_idx],
                    "macro_time": time_assignments[idx],
                    "type": "transfer",  # TODO(扩展): 第5批 RAG 场景可覆盖边类型
                    "initial_tags": {},   # TODO(扩展): 第5批 RAG 可注入初始标签
                })

            # --- Step 5: 计算度分布（C 底层，极快）---
            degree_map = self._compute_degree_map(raw_edges, node_ids, n)

            # --- Step 6: 组装 metadata ---
            first_label = get_macro_block_label(1, mbu)
            last_label = get_macro_block_label(total_blocks, mbu)
            metadata = {
                "total_nodes": n,
                "total_edges": actual_edge_count,
                "time_span": "{first} to {last}".format(first=first_label, last=last_label),
                "total_time_blocks": total_blocks,
                "macro_block_unit": mbu,
                "micro_granularity": mg,
                "edges_per_block_avg": round(actual_edge_count / max(total_blocks, 1), 2),
                "generator_type": "{eng}_barabasi_albert".format(eng=self.engine),
                "gamma": g,
                "hub_ratio": hr,
                "burstiness": burstiness,
            }

        # --- 完成日志 ---
        log_event(1, "skeleton_complete",
                  "骨架生成完成: {n} 节点, {e} 边, {tb} 时间块, 耗时 {t:.3f}s".format(
                      n=n, e=actual_edge_count, tb=total_blocks, t=timer.elapsed),
                  {"metadata": metadata})

        skeleton = {
            "nodes": node_ids,
            "macro_edges": macro_edges,
            "metadata": metadata,
            "degree_map": degree_map,
        }

        return skeleton

    def generate_from_config(self, config_dict):
        # type: (Dict[str, Any]) -> Dict[str, Any]
        """
        从完整配置字典生成骨架（便于与服务器集成）

        输入：
          config_dict: 由 config.get_full_config(overrides) 返回的配置字典
        输出：
          skeleton 字典（同 generate_power_law_skeleton）
        调用时机：server.py 收到 start_pipeline 后调用
        """
        return self.generate_power_law_skeleton(
            num_nodes=config_dict.get("num_nodes"),
            num_edges=config_dict.get("num_edges"),
            gamma=config_dict.get("gamma"),
            hub_ratio=config_dict.get("hub_ratio"),
            time_span_value=config_dict.get("time_span_value"),
            time_span_unit=config_dict.get("time_span_unit"),
            macro_block_unit=config_dict.get("macro_block_unit"),
            micro_granularity=config_dict.get("micro_granularity"),
            burstiness=config_dict.get("burstiness", 0.3),
        )

    # ============================================================
    # 度分布预览（纯数学，不生成图）
    # ============================================================

    @staticmethod
    def preview_degree_distribution(gamma, num_nodes, num_points=50):
        # type: (float, int, int) -> List[List[float]]
        """
        根据幂律指数生成理论度分布预览曲线（纯数学计算）

        输入：
          gamma: 幂律指数
          num_nodes: 节点数（决定度值范围上限）
          num_points: 采样点数（默认 50，足够画曲线）
        输出：
          [[k, P(k)], ...] 列表，约 num_points 个采样点
          k = 度值，P(k) = 该度值出现的概率
        调用时机：用户拖动 γ 滑块时实时预览，WebSocket 请求-响应

        数学原理：
          幂律分布 P(k) ∝ k^(-γ)
          归一化后 P(k) = k^(-γ) / Σ_{j=1}^{k_max} j^(-γ)
          k_max 由 num_nodes 近似估计
        """
        # 度值范围：1 到 sqrt(num_nodes) * 2（经验上限）
        k_max = max(10, int(math.sqrt(num_nodes) * 2))

        # 对数均匀采样 k 值（这样 log-log 图上点分布均匀）
        k_values = np.logspace(0, math.log10(k_max), num=num_points)
        k_values = np.unique(np.round(k_values).astype(int))
        k_values = k_values[k_values >= 1]  # 度至少为 1

        # 计算未归一化概率
        raw_probs = np.power(k_values.astype(float), -gamma)

        # 归一化
        total = np.sum(raw_probs)
        if total > 0:
            probs = raw_probs / total
        else:
            probs = raw_probs

        # 组装为 [[k, P(k)], ...] 格式
        points = []
        for k, p in zip(k_values.tolist(), probs.tolist()):
            points.append([int(k), round(p, 8)])

        return points

    # ============================================================
    # 度分布获取（从已生成的 skeleton 中提取）
    # ============================================================

    @staticmethod
    def get_degree_distribution(skeleton):
        # type: (Dict[str, Any]) -> List[List[int]]
        """
        从 skeleton 中统计实际度分布（用于 log-log 图表）

        输入：
          skeleton: 由 generate_power_law_skeleton 返回的字典
        输出：
          [[degree, count], ...] 列表，按 degree 升序
          degree = 度值，count = 有多少节点具有该度值
        调用时机：骨架生成完成后，前端渲染度分布图
        """
        degree_map = skeleton.get("degree_map", {})
        # 统计每个度值有多少节点
        degree_counts = Counter(degree_map.values())
        # 按度值排序
        result = sorted([[k, v] for k, v in degree_counts.items()])
        return result

    # ============================================================
    # 内部方法：BA 图生成
    # ============================================================

    def _generate_ba_graph(self, num_nodes, target_edges, gamma):
        # type: (int, int, float) -> List[Tuple[int, int]]
        """
        使用 Barabási-Albert 模型生成有向幂律图

        输入：
          num_nodes: 节点数
          target_edges: 期望边数（BA 模型用 m 参数近似）
          gamma: 幂律指数（igraph 的 power 参数）
        输出：
          边列表 [(source_idx, target_idx), ...]，索引从 0 开始
        调用时机：generate_power_law_skeleton 内部调用

        关于 BA 模型的 m 参数：
          BA 模型中每个新加入的节点连接 m 条边到已有节点
          最终边数约等于 m * (num_nodes - m)
          所以 m ≈ target_edges / num_nodes（向上取整，至少为 1）
        """
        # 计算 BA 模型的 m 参数
        # 修复 #5: BA 模型实际边数 ≈ m * (n - m - 1) + m*(m+1)/2
        # 当 n >> m 时，近似为 m * n
        # 但精确解需要用 m * (n - m) 来反推
        # m = target_edges / (n - m) → 解方程 m² - n*m + target_edges = 0
        # m = (n - sqrt(n² - 4*target_edges)) / 2
        discriminant = num_nodes * num_nodes - 4 * target_edges
        if discriminant > 0:
            m = int(math.ceil((num_nodes - math.sqrt(discriminant)) / 2.0))
        else:
            # target_edges > n²/4，用上限
            m = num_nodes // 2
        m = max(1, m)
        # m 不能超过 num_nodes - 1（否则 igraph 报错）
        m = min(m, max(1, num_nodes - 1))

        logger.info("BA 图参数: n=%d, m=%d, gamma=%.2f, engine=%s",
                     num_nodes, m, gamma, self.engine)

        if self.engine == "igraph":
            return self._generate_ba_igraph(num_nodes, m, gamma)
        elif self.engine == "networkx":
            return self._generate_ba_networkx(num_nodes, m)
        else:
            # 最终回退：手动实现简化版 BA
            logger.warning("无图引擎可用，使用简化 BA 实现")
            return self._generate_ba_fallback(num_nodes, m)

    def _generate_ba_igraph(self, n, m, gamma):
        # type: (int, int, float) -> List[Tuple[int, int]]
        """
        igraph C 底层 BA 图生成

        PERF: 百万节点 <3 秒，这是 SAGA 性能的关键保障
        igraph.Graph.Barabasi 参数说明：
          n: 节点数
          m: 每个新节点的出边数
          power: 优先连接指数（对应幂律 gamma，越大 hub 效应越弱）
          directed: True 生成有向图
          implementation: "psumtree" 是最快的实现
        """
        # PERF: igraph C 底层执行，百万节点约 1-3 秒
        graph = ig.Graph.Barabasi(
            n=n,
            m=m,
            power=gamma,          # 优先连接指数
            directed=True,        # 有向图
            implementation="psumtree",  # 最快的内部实现
        )
        # get_edgelist() 直接返回 C 数组的 Python 视图，极快
        edges = graph.get_edgelist()
        logger.info("igraph 生成完成: %d 节点, %d 边", n, len(edges))
        return edges

    def _generate_ba_networkx(self, n, m):
        # type: (int, int) -> List[Tuple[int, int]]
        """
        NetworkX 回退方案（纯 Python，较慢）

        注意：networkx 的 barabasi_albert_graph 生成无向图
        我们手动加方向：每条边随机确定方向
        """
        graph = nx.barabasi_albert_graph(n, m)
        edges = []
        for u, v in graph.edges():
            # 随机确定方向
            if self._rng.random() < 0.5:
                edges.append((u, v))
            else:
                edges.append((v, u))
        logger.info("networkx 生成完成: %d 节点, %d 边", n, len(edges))
        return edges

    def _generate_ba_fallback(self, n, m):
        # type: (int, int) -> List[Tuple[int, int]]
        """
        简化 BA 模型回退实现（纯 Python，不依赖任何图库）

        实现原理：
        1. 初始 m+1 个节点全连接
        2. 每个新节点按"优先连接"概率连 m 条边
        3. 优先连接 = 节点度数越高，被连接概率越大
        """
        edges = []
        # 初始完全子图
        for i in range(min(m + 1, n)):
            for j in range(i + 1, min(m + 1, n)):
                edges.append((i, j))

        if n <= m + 1:
            return edges

        # 度数数组（用于优先连接采样）
        degrees = [0] * n
        for u, v in edges:
            degrees[u] += 1
            degrees[v] += 1

        # 逐个添加新节点
        for new_node in range(m + 1, n):
            # 按度数加权采样 m 个目标节点
            existing = list(range(new_node))
            weights = [degrees[i] + 1 for i in existing]  # +1 避免零权重
            total_w = sum(weights)
            probs = [w / total_w for w in weights]

            # 不放回采样 m 个目标
            targets = set()
            attempts = 0
            while len(targets) < min(m, new_node) and attempts < m * 10:
                r = self._rng.random()
                cumsum = 0.0
                for i, p in enumerate(probs):
                    cumsum += p
                    if r <= cumsum:
                        targets.add(existing[i])
                        break
                attempts += 1

            for t in targets:
                edges.append((new_node, t))
                degrees[new_node] += 1
                degrees[t] += 1

        logger.info("fallback BA 生成完成: %d 节点, %d 边", n, len(edges))
        return edges

    # ============================================================
    # 内部方法：节点 ID 生成
    # ============================================================

    def _generate_node_ids(self, num_nodes):
        # type: (int) -> List[str]
        """
        生成标准化的节点 ID 列表

        格式：N_XXXX（根据节点数自动调整位数）
        示例：N_0001, N_0002, ..., N_1000
              N_000001, ..., N_100000（10万节点时6位）

        为什么不用纯数字？
        因为字符串 ID 在 JSON 中更清晰，且可以附加场景前缀（如 "ACCT_001"）
        TODO(扩展): 第5批可以根据 RAG 场景生成更有语义的 ID 前缀
        """
        # 自动计算所需位数
        digits = max(4, len(str(num_nodes)))
        fmt = "N_{idx:0{d}d}".format(idx=0, d=digits)  # 测试格式

        node_ids = []
        for i in range(num_nodes):
            # Python 3.8 兼容的格式化方式
            node_id = "N_" + str(i + 1).zfill(digits)
            node_ids.append(node_id)

        return node_ids

    # ============================================================
    # 内部方法：宏观时间分配（时间是第一等公民！）
    # ============================================================

    def _assign_macro_times(self, num_edges, total_blocks, macro_block_unit, burstiness):
        # type: (int, int, str, float) -> List[str]
        """
        为每条宏观边分配 macro_time 时间块标签

        输入：
          num_edges: 边总数
          total_blocks: 时间块总数
          macro_block_unit: 粒度单位（决定标签前缀如 Day_/Hour_/Week_）
          burstiness: 阵发性指数 [0, 1]
                      0 = 完全均匀（每个时间块边数相同）
                      1 = 极度集中（大部分边集中在少数时间块）
        输出：
          长度为 num_edges 的标签列表
          如 ["Day_1", "Day_3", "Day_1", "Day_5", ...]
        调用时机：generate_power_law_skeleton 内部调用

        时间分配策略（非均匀！）：
        1. 基础权重：每个时间块初始权重为 1.0
        2. 阵发性叠加：用 Dirichlet 分布生成不均匀权重
           alpha 越小 → 权重越不均匀 → 阵发性越强
        3. 按权重采样每条边的时间块归属

        CONFIG: 这个函数是 SAGA 时间模式最值得调优的地方
        TODO(扩展): 第5批可以根据 RAG 规则注入周期模式
                    （如金融场景的工作日/周末差异、月初月末高峰）
        """
        if total_blocks <= 0:
            return ["Block_1"] * num_edges

        # --- Step 1: 生成时间块权重 ---
        # burstiness → Dirichlet alpha 参数的映射
        # burstiness=0 → alpha 很大 → 权重几乎均匀
        # burstiness=1 → alpha 很小 → 权重极不均匀
        # 映射函数：alpha = 10^(2 * (1 - burstiness))
        # burstiness=0 → alpha=100（近似均匀）
        # burstiness=0.5 → alpha=10（轻度不均）
        # burstiness=1.0 → alpha=1（极度不均）
        alpha = math.pow(10, 2.0 * (1.0 - max(0.0, min(1.0, burstiness))))

        # Dirichlet 分布生成 total_blocks 个权重（和为 1）
        # 每个权重代表该时间块被分配到边的概率
        weights = np.random.dirichlet([alpha] * total_blocks)

        # --- Step 2: 根据权重为每条边采样时间块 ---
        # numpy 的 multinomial 采样比 Python 循环快 100 倍以上
        # PERF: 百万边的采样约 0.01 秒
        block_indices = np.random.choice(
            total_blocks,
            size=num_edges,
            p=weights,
        )

        # --- Step 3: 转换为标签字符串 ---
        # 预先生成所有标签（避免循环内重复计算）
        labels = [get_macro_block_label(i + 1, macro_block_unit) for i in range(total_blocks)]
        time_assignments = [labels[bi] for bi in block_indices]

        # --- 日志：输出时间块分配统计 ---
        block_counts = Counter(block_indices)
        # 找出边最多和最少的时间块
        if block_counts:
            max_block = max(block_counts.values())
            min_block = min(block_counts.values())
            avg_block = num_edges / total_blocks
            logger.info(
                "时间分配: %d 块, burstiness=%.2f, "
                "每块边数 min=%d / avg=%.1f / max=%d",
                total_blocks, burstiness, min_block, avg_block, max_block
            )

        return time_assignments

    # ============================================================
    # 内部方法：度分布计算
    # ============================================================

    def _compute_degree_map(self, raw_edges, node_ids, num_nodes):
        # type: (List[Tuple[int, int]], List[str], int) -> Dict[str, int]
        """
        计算每个节点的度数（入度+出度）

        输入：
          raw_edges: 原始边列表 [(src_idx, tgt_idx), ...]
          node_ids: 节点 ID 列表
          num_nodes: 节点总数
        输出：
          { "N_0001": 15, "N_0002": 3, ... }
        调用时机：generate_power_law_skeleton 内部调用

        用途：前端根据度数缩放节点大小（度高=节点大）
        """
        # 使用 numpy 快速统计
        if len(raw_edges) == 0:
            return {nid: 0 for nid in node_ids}

        edge_arr = np.array(raw_edges, dtype=np.int64)
        # 统计出度
        out_degrees = np.bincount(edge_arr[:, 0], minlength=num_nodes)
        # 统计入度
        in_degrees = np.bincount(edge_arr[:, 1], minlength=num_nodes)
        # 总度 = 入度 + 出度
        total_degrees = out_degrees + in_degrees

        degree_map = {}
        for i in range(num_nodes):
            degree_map[node_ids[i]] = int(total_degrees[i])

        return degree_map

    # ============================================================
    # 骨架持久化（保存为 JSON 文件）
    # ============================================================

    @staticmethod
    def save_skeleton(skeleton, filepath):
        # type: (Dict[str, Any], str) -> None
        """
        将骨架保存为 JSON 文件

        输入：
          skeleton: 骨架字典
          filepath: 输出文件路径
        调用时机：Pipeline 完成后保存中间产物（调试用）
        """
        try:
            import orjson
            data = orjson.dumps(skeleton, option=orjson.OPT_INDENT_2)
            with open(filepath, "wb") as f:
                f.write(data)
        except ImportError:
            import json
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(skeleton, f, ensure_ascii=False, indent=2)

        log_event(1, "skeleton_saved",
                  "骨架已保存: {p}".format(p=filepath))

    @staticmethod
    def load_skeleton(filepath):
        # type: (str) -> Dict[str, Any]
        """
        从 JSON 文件加载骨架

        输入：filepath 文件路径
        输出：skeleton 字典
        调用时机：调试时跳过 Phase 1 直接加载已有骨架
        """
        try:
            import orjson
            with open(filepath, "rb") as f:
                return orjson.loads(f.read())
        except ImportError:
            import json
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)

    # ============================================================
    # 骨架统计信息（用于前端 StatsPanel）
    # ============================================================

    @staticmethod
    def get_skeleton_stats(skeleton):
        # type: (Dict[str, Any]) -> Dict[str, Any]
        """
        从骨架中提取统计摘要

        输出：
          {
            "total_nodes": int,
            "total_edges": int,
            "total_time_blocks": int,
            "avg_degree": float,
            "max_degree": int,
            "min_degree": int,
            "edges_per_block": { "Day_1": 15, "Day_2": 8, ... },
            "hub_nodes": ["N_0001", "N_0023", ...]  # 度数 top 1%
          }
        调用时机：骨架生成完成后，推送给前端展示
        """
        degree_map = skeleton.get("degree_map", {})
        macro_edges = skeleton.get("macro_edges", [])
        metadata = skeleton.get("metadata", {})

        degrees = list(degree_map.values())
        avg_deg = sum(degrees) / max(len(degrees), 1)
        max_deg = max(degrees) if degrees else 0
        min_deg = min(degrees) if degrees else 0

        # 统计每个时间块的边数
        block_counts = Counter(e["macro_time"] for e in macro_edges)

        # 找出 hub 节点（度数 top 1%）
        if degrees:
            threshold = sorted(degrees, reverse=True)[max(0, len(degrees) // 100)]
            hub_nodes = [nid for nid, d in degree_map.items() if d >= threshold]
        else:
            hub_nodes = []

        return {
            "total_nodes": metadata.get("total_nodes", len(skeleton.get("nodes", []))),
            "total_edges": metadata.get("total_edges", len(macro_edges)),
            "total_time_blocks": metadata.get("total_time_blocks", len(block_counts)),
            "avg_degree": round(avg_deg, 2),
            "max_degree": max_deg,
            "min_degree": min_deg,
            "edges_per_block": dict(block_counts),
            "hub_nodes": hub_nodes[:20],  # 最多返回 20 个 hub 节点 ID
        }
