# ============================================================
# SAGA CLI - 自动统计计算
# 用途：从 pipeline 输出的 final_graph 中计算论文所需的全部指标
#       度分布拟合、时间分布、异常率、聚类系数等
# 修复: #3(幂律拟合) #4(聚类系数) #11(大规模拟合) #12(聚类大规模)
#       #13(burstiness) #14(区分 input/fitted gamma)
# ============================================================

import math
from collections import Counter
from typing import Dict, Any, List, Tuple

import numpy as np

from config import parse_micro_time_key
from utils.logger import get_logger

logger = get_logger("saga.utils.stats")


def compute_statistics(final_graph, timings=None, config=None):
    # type: (Dict[str, Any], Dict, Dict) -> Dict[str, Any]
    """
    计算完整统计指标，输出即 stats.json 的内容

    输入:
      final_graph: pipeline.run() 返回的字典 { nodes, edges, statistics }
      timings: pipeline.timings 字典（Phase 耗时）
      config: 运行配置（记录 LLM provider/model）
    输出:
      统计指标字典
    """
    nodes = final_graph.get("nodes", [])
    edges = final_graph.get("edges", [])
    raw_stats = final_graph.get("statistics", {})

    result = {}

    # === 结构指标 ===
    degree_seq = _compute_degree_sequence(nodes, edges)
    result["degree_distribution"] = _degree_distribution(degree_seq)

    gamma, r2, ks = fit_power_law(degree_seq)
    # 修复 #14: 区分用户设置的 gamma（input）和拟合出的 gamma（fitted）
    result["fitted_gamma"] = round(gamma, 4)
    result["power_law_r2"] = round(r2, 4)
    result["power_law_ks"] = round(ks, 4)
    # 保留旧字段名兼容（但新 summary.csv 用 fitted_gamma）
    result["power_law_gamma"] = round(gamma, 4)

    clustering = _compute_clustering_safe(nodes, edges)
    result["clustering_coefficient"] = round(clustering, 6)

    comp_info = _compute_components(nodes, edges)
    result["num_components"] = comp_info["num_components"]
    result["largest_component_ratio"] = round(comp_info["largest_ratio"], 4)

    # === 时间指标 ===
    result["temporal_density"] = _temporal_density(edges)
    result["intraday_distribution"] = _intraday_distribution(edges)
    result["temporal_burstiness"] = round(_burstiness(edges), 4)

    # === 属性指标 ===
    amounts = [e.get("amt", 0) for e in edges if e.get("amt", 0) > 0]
    if amounts:
        arr = np.array(amounts, dtype=float)
        result["amount_stats"] = {
            "mean": round(float(np.mean(arr)), 2),
            "std": round(float(np.std(arr)), 2),
            "median": round(float(np.median(arr)), 2),
            "min": int(np.min(arr)),
            "max": int(np.max(arr)),
            "skew": round(float(_skew(arr)), 4),
            "kurtosis": round(float(_kurtosis(arr)), 4),
        }
    else:
        result["amount_stats"] = {}

    result["anomaly_rate"] = round(
        raw_stats.get("anomaly_edges", 0) / max(len(edges), 1), 4
    )
    result["anomaly_count"] = raw_stats.get("anomaly_edges", 0)
    result["normal_count"] = raw_stats.get("normal_edges", 0)
    result["anomaly_breakdown"] = raw_stats.get("anomaly_breakdown", {})

    # === 运行指标 ===
    result["total_nodes"] = len(nodes)
    result["total_edges"] = len(edges)

    if timings:
        result["phase_s_ms"] = round(timings.get("phase_s_ms", 0), 2)
        result["phase_a1_ms"] = round(timings.get("phase_a1_ms", 0), 2)
        result["phase_g_ms"] = round(timings.get("phase_g_ms", 0), 2)
        result["phase_a2_ms"] = round(timings.get("phase_a2_ms", 0), 2)
        result["total_ms"] = round(timings.get("total_ms", 0), 2)

    if config:
        result["llm_provider"] = config.get("llm_provider", "unknown")
        result["llm_model"] = config.get("llm_model", "unknown")

    return result


# ============================================================
# 幂律拟合 — 修复 #3/#11
# ============================================================

def fit_power_law(degree_sequence):
    # type: (List[int]) -> Tuple[float, float, float]
    """
    对度序列做幂律拟合，返回 (gamma, R2, KS)。

    修复 #3/#11: 
    1. 过滤 degree=0 的节点（孤立节点不参与幂律拟合）
    2. 当唯一度值太少时（<5），用 MLE 估计
    3. 大规模 BA 图 m>=5 时度分布应有足够唯一度值
    
    MLE 估计公式（连续近似）：
      gamma_hat = 1 + n / sum(ln(k_i / k_min))
    """
    if len(degree_sequence) < 5:
        return (0.0, 0.0, 1.0)

    # 过滤 degree=0（孤立节点不参与幂律）
    nonzero = [d for d in degree_sequence if d > 0]
    if len(nonzero) < 5:
        return (0.0, 0.0, 1.0)

    degrees, counts = np.unique(nonzero, return_counts=True)

    # 方法 1: 唯一度值足够多（>=5），用加权 log-log 线性回归
    if len(degrees) >= 5:
        probs = counts.astype(float) / counts.sum()
        log_k = np.log10(degrees.astype(float))
        log_p = np.log10(probs)

        # 加权最小二乘（高频度值权重大，抗低频噪声）
        weights = np.sqrt(counts.astype(float))
        W = np.diag(weights)
        A = np.column_stack([log_k, np.ones_like(log_k)])
        WA = W @ A
        Wy = W @ log_p
        try:
            coeffs = np.linalg.lstsq(WA, Wy, rcond=None)[0]
            slope = coeffs[0]
            intercept = coeffs[1]
        except np.linalg.LinAlgError:
            slope, intercept = np.polyfit(log_k, log_p, 1)

        y_pred = slope * log_k + intercept
        ss_res = np.sum((log_p - y_pred) ** 2)
        ss_tot = np.sum((log_p - np.mean(log_p)) ** 2)
        r2 = max(0.0, 1.0 - ss_res / max(ss_tot, 1e-10))
        gamma = -slope

    # 方法 2: 唯一度值 3-4 个，用 MLE
    elif len(degrees) >= 3:
        arr = np.array(nonzero, dtype=float)
        k_min = float(np.min(arr))
        if k_min < 1:
            k_min = 1.0
        # MLE: gamma = 1 + n / sum(ln(k_i / k_min))
        log_ratios = np.log(arr / k_min)
        log_ratios = log_ratios[log_ratios > 0]
        if len(log_ratios) > 0:
            gamma = 1.0 + len(log_ratios) / np.sum(log_ratios)
        else:
            gamma = 0.0

        # MLE 结果的 R2
        if gamma > 1:
            probs = counts.astype(float) / counts.sum()
            log_k = np.log10(degrees.astype(float))
            log_p = np.log10(probs)
            predicted_log_p = -gamma * log_k + (gamma * np.log10(degrees[0]) + np.log10(probs[0]))
            ss_res = np.sum((log_p - predicted_log_p) ** 2)
            ss_tot = np.sum((log_p - np.mean(log_p)) ** 2)
            r2 = max(0.0, 1.0 - ss_res / max(ss_tot, 1e-10))
        else:
            r2 = 0.0
    else:
        return (0.0, 0.0, 1.0)

    # KS 统计量
    ks = 0.0
    try:
        from scipy.stats import kstest
        if gamma > 1:
            ks_stat, _ = kstest(nonzero, 'pareto', args=(gamma - 1,))
            ks = float(ks_stat)
    except Exception:
        pass

    logger.info("幂律拟合: gamma=%.4f, R2=%.4f, KS=%.4f, 唯一度值数=%d",
                 gamma, r2, ks, len(degrees))

    return (gamma, r2, ks)


# ============================================================
# 辅助计算函数
# ============================================================

def _compute_degree_sequence(nodes, edges):
    # type: (List[Dict], List[Dict]) -> List[int]
    """计算度序列（入度+出度）"""
    deg = Counter()
    for e in edges:
        u = e.get("u", "")
        v = e.get("v", "")
        if u:
            deg[u] += 1
        if v:
            deg[v] += 1
    # 包含度为 0 的节点
    for n in nodes:
        nid = n.get("id", "")
        if nid not in deg:
            deg[nid] = 0
    return list(deg.values())


def _degree_distribution(degree_seq):
    # type: (List[int]) -> List[List[int]]
    """度分布: [[degree, count], ...]"""
    c = Counter(degree_seq)
    return sorted([[k, v] for k, v in c.items()])


def _compute_clustering_safe(nodes, edges):
    # type: (List[Dict], List[Dict]) -> float
    """
    计算聚类系数 — 修复 #4/#12

    用 transitivity_local_undirected 的均值替代全局 transitivity_undirected
    BA 图全局聚类系数接近 0 是正常的（三角形极少），
    但局部聚类系数均值能捕捉到更多结构信息
    """
    try:
        import igraph as ig
        node_ids = [n.get("id", "") for n in nodes]
        id_map = {nid: i for i, nid in enumerate(node_ids)}
        edge_tuples = []
        for e in edges:
            u = e.get("u", "")
            v = e.get("v", "")
            if u in id_map and v in id_map:
                edge_tuples.append((id_map[u], id_map[v]))
        if not edge_tuples:
            return 0.0

        # 有向图转无向（合并双向边、去自环和重边）
        g = ig.Graph(n=len(node_ids), edges=edge_tuples, directed=True)
        g_undirected = g.as_undirected(mode="collapse")
        g_undirected = g_undirected.simplify()

        # 局部聚类系数均值（度<2 的节点算 0）
        local_cc = g_undirected.transitivity_local_undirected(mode="zero")
        if local_cc:
            avg_cc = sum(local_cc) / len(local_cc)
        else:
            avg_cc = 0.0

        logger.info("聚类系数: 局部平均=%.6f, 节点=%d, 边=%d",
                     avg_cc, g_undirected.vcount(), g_undirected.ecount())
        return avg_cc
    except Exception as ex:
        logger.warning("聚类系数计算失败: %s", str(ex))
        return 0.0


def _compute_components(nodes, edges):
    # type: (List[Dict], List[Dict]) -> Dict[str, Any]
    """连通分量统计"""
    try:
        import igraph as ig
        node_ids = [n.get("id", "") for n in nodes]
        id_map = {nid: i for i, nid in enumerate(node_ids)}
        edge_tuples = []
        for e in edges:
            u = e.get("u", "")
            v = e.get("v", "")
            if u in id_map and v in id_map:
                edge_tuples.append((id_map[u], id_map[v]))
        g = ig.Graph(n=len(node_ids), edges=edge_tuples, directed=True)
        components = g.connected_components(mode="weak")
        sizes = [len(c) for c in components]
        largest = max(sizes) if sizes else 0
        return {
            "num_components": len(components),
            "largest_ratio": largest / max(len(node_ids), 1),
        }
    except Exception:
        return {"num_components": 0, "largest_ratio": 0.0}


def _temporal_density(edges):
    # type: (List[Dict]) -> List[List]
    """时间块密度: [[block_label, count], ...]"""
    block_counts = Counter()
    for e in edges:
        t = e.get("time", "")
        parts = t.split("_")
        if len(parts) >= 2:
            block = "{p}_{d}".format(p=parts[0], d=parts[1])
            block_counts[block] += 1
    return sorted(block_counts.items(), key=lambda x: parse_micro_time_key(x[0] + "_00:00"))


def _intraday_distribution(edges):
    # type: (List[Dict]) -> List[List[int]]
    """
    日内小时分布: [[hour, count], ...] 共 24 项
    修复 #13: 直接从字符串解析，不依赖 parse_micro_time_key
    """
    hour_counts = [0] * 24
    for e in edges:
        t = e.get("time", "")
        # 格式: "Day_X_HH:MM" 或 "Day_X_HH:MM:SS" 或 "Day_X_HH"
        parts = t.split("_")
        if len(parts) >= 3:
            time_part = parts[2]
            try:
                hour = int(time_part.split(":")[0])
                if 0 <= hour <= 23:
                    hour_counts[hour] += 1
            except (ValueError, IndexError):
                pass
    return [[h, c] for h, c in enumerate(hour_counts)]


def _burstiness(edges):
    # type: (List[Dict]) -> float
    """
    阵发性系数 B = (sigma - mu) / (sigma + mu)
    修复 #13: 基于 Day 级别分组
    B in [-1, 1]，0=均匀，正值=集中，负值=规律
    """
    block_counts = Counter()
    for e in edges:
        t = e.get("time", "")
        parts = t.split("_")
        if len(parts) >= 2:
            block = "{p}_{d}".format(p=parts[0], d=parts[1])
            block_counts[block] += 1

    if len(block_counts) < 2:
        return 0.0

    vals = np.array(list(block_counts.values()), dtype=float)
    mu = np.mean(vals)
    sigma = np.std(vals)
    if mu + sigma == 0:
        return 0.0
    return float((sigma - mu) / (sigma + mu))


def _skew(arr):
    # type: (np.ndarray) -> float
    """偏度"""
    n = len(arr)
    if n < 3:
        return 0.0
    m = np.mean(arr)
    s = np.std(arr)
    if s == 0:
        return 0.0
    return float(np.mean(((arr - m) / s) ** 3))


def _kurtosis(arr):
    # type: (np.ndarray) -> float
    """峰度（超额）"""
    n = len(arr)
    if n < 4:
        return 0.0
    m = np.mean(arr)
    s = np.std(arr)
    if s == 0:
        return 0.0
    return float(np.mean(((arr - m) / s) ** 4) - 3.0)
