#!/usr/bin/env python3
# ============================================================
# SAGA 对比实验：SAGA vs NetworkX vs LDBC-SNB
# 对比维度：生成速度、度分布保真度、可控性
# 运行：python3 experiments/run_comparison.py
# ============================================================
import csv
import math
import os
import sys
import time
from collections import Counter

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OUTPUT_DIR = os.environ.get("SAGA_OUTPUT_DIR", "./output/comparison")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 测试规模
SCALES = [
    (100,    500),
    (500,    2500),
    (1000,   5000),
    (5000,   25000),
    (10000,  50000),
    (50000,  250000),
    (100000, 500000),
]


def power_law_r2(degrees, gamma_target):
    """计算度分布的幂律拟合 R²"""
    deg_count = Counter(degrees)
    if len(deg_count) < 3:
        return 0.0
    ks = np.array(sorted(deg_count.keys()), dtype=float)
    cs = np.array([deg_count[int(k)] for k in ks], dtype=float)
    mask = (ks > 0) & (cs > 0)
    if mask.sum() < 3:
        return 0.0
    log_k = np.log10(ks[mask])
    log_c = np.log10(cs[mask])
    coeffs = np.polyfit(log_k, log_c, 1)
    fitted = np.polyval(coeffs, log_k)
    ss_res = np.sum((log_c - fitted) ** 2)
    ss_tot = np.sum((log_c - np.mean(log_c)) ** 2)
    return max(0.0, 1 - ss_res / ss_tot) if ss_tot > 0 else 0.0


# ============================================================
# 生成器 1：NetworkX BA 模型
# ============================================================
def run_networkx(n, target_edges, gamma):
    """NetworkX Barabási-Albert 随机图"""
    import networkx as nx
    m = max(1, target_edges // n)
    t0 = time.perf_counter()
    G = nx.barabasi_albert_graph(n, m, seed=42)
    elapsed = time.perf_counter() - t0
    degrees = [d for _, d in G.degree()]
    return {
        "generator": "NetworkX-BA",
        "nodes": n,
        "edges": G.number_of_edges(),
        "target_edges": target_edges,
        "time_sec": round(elapsed, 4),
        "power_law_r2": round(power_law_r2(degrees, gamma), 4),
        "has_timestamps": False,
        "has_semantics": False,
        "has_anomaly_labels": False,
        "anomaly_rate_control": "N/A",
    }


# ============================================================
# 生成器 2：igraph BA 模型（SAGA 用的底层引擎）
# ============================================================
def run_igraph(n, target_edges, gamma):
    """igraph Barabási-Albert（C 底层）"""
    import igraph as ig
    m = max(1, target_edges // n)
    t0 = time.perf_counter()
    G = ig.Graph.Barabasi(n=n, m=m, power=gamma, directed=True)
    elapsed = time.perf_counter() - t0
    degrees = G.degree()
    return {
        "generator": "igraph-BA",
        "nodes": n,
        "edges": G.ecount(),
        "target_edges": target_edges,
        "time_sec": round(elapsed, 4),
        "power_law_r2": round(power_law_r2(degrees, gamma), 4),
        "has_timestamps": False,
        "has_semantics": False,
        "has_anomaly_labels": False,
        "anomaly_rate_control": "N/A",
    }


# ============================================================
# 生成器 3：SAGA（完整 Pipeline，Mock 模式）
# ============================================================
def run_saga_mock(n, target_edges, gamma, anomaly_rate=0.1):
    """SAGA 完整 Pipeline（Mock 模式，不调 LLM）"""
    import asyncio
    from core.pipeline import SAGAPipeline
    from utils.stats import compute_statistics

    config = {
        "num_nodes": n, "num_edges": target_edges,
        "time_span_days": 7, "power_law_gamma": gamma,
        "hub_ratio": 0.1, "macro_block_unit": "day",
        "micro_granularity": "minute", "domain": "finance",
        "rag_level": "full", "initial_balance": 5000,
        "anomaly_rate": anomaly_rate,
        "llm_provider": "mock", "llm_concurrency": 10,
        "micro_edges_min": 1, "micro_edges_max": 1, "max_retries": 3,
        "risk_threshold_medium": 1, "risk_threshold_high": 3,
        "freeze_threshold": 5, "skeleton_mode": "power_law",
        "injection_mode": "llm", "skip_alignment": False,
        "seed": 42,
    }
    t0 = time.perf_counter()
    result = asyncio.run(SAGAPipeline(config).run())
    elapsed = time.perf_counter() - t0

    stats = compute_statistics(result, config=config)
    edges = result["edges"]
    anom = sum(1 for e in edges if e.get("tag", "normal") != "normal")
    actual_rate = anom / max(len(edges), 1)

    return {
        "generator": "SAGA-Mock",
        "nodes": n,
        "edges": len(edges),
        "target_edges": target_edges,
        "time_sec": round(elapsed, 4),
        "power_law_r2": round(stats.get("power_law_r2", 0), 4),
        "has_timestamps": True,
        "has_semantics": True,
        "has_anomaly_labels": True,
        "anomaly_rate_control": "{:.1f}% (target {:.0f}%)".format(actual_rate * 100, anomaly_rate * 100),
    }


# ============================================================
# 生成器 4：SAGA（完整 Pipeline，LLM 模式）— 修复 #9
# ============================================================
def run_saga_llm(n, target_edges, gamma, anomaly_rate=0.1):
    """SAGA 完整 Pipeline（vLLM 模式）"""
    import asyncio
    from core.pipeline import SAGAPipeline
    from utils.stats import compute_statistics

    config = {
        "num_nodes": n, "num_edges": target_edges,
        "time_span_days": 7, "power_law_gamma": gamma,
        "hub_ratio": 0.1, "macro_block_unit": "day",
        "micro_granularity": "minute", "domain": "finance",
        "rag_level": "full", "initial_balance": 5000,
        "anomaly_rate": anomaly_rate,
        "llm_provider": "vllm", "llm_concurrency": 256,
        "micro_edges_min": 1, "micro_edges_max": 1, "max_retries": 3,
        "risk_threshold_medium": 1, "risk_threshold_high": 3,
        "freeze_threshold": 5, "skeleton_mode": "power_law",
        "injection_mode": "llm", "skip_alignment": False,
        "seed": 42,
    }
    t0 = time.perf_counter()
    result = asyncio.run(SAGAPipeline(config).run())
    elapsed = time.perf_counter() - t0

    stats = compute_statistics(result, config=config)
    edges = result["edges"]
    anom = sum(1 for e in edges if e.get("tag", "normal") != "normal")
    actual_rate = anom / max(len(edges), 1)

    return {
        "generator": "SAGA-LLM",
        "nodes": n,
        "edges": len(edges),
        "target_edges": target_edges,
        "time_sec": round(elapsed, 4),
        "power_law_r2": round(stats.get("power_law_r2", 0), 4),
        "has_timestamps": True,
        "has_semantics": True,
        "has_anomaly_labels": True,
        "anomaly_rate_control": "{:.1f}% (target {:.0f}%)".format(actual_rate * 100, anomaly_rate * 100),
    }


# ============================================================
# 主程序
# ============================================================
def main():
    print("=" * 70)
    print("  SAGA Comparison Experiment")
    print("  SAGA vs NetworkX vs igraph")
    print("=" * 70)

    results = []

    for n, e in SCALES:
        print("\n--- Scale: {:,} nodes / {:,} edges ---".format(n, e))

        # NetworkX
        try:
            r = run_networkx(n, e, 2.5)
            print("  NetworkX:  {:.3f}s  R2={:.3f}".format(r["time_sec"], r["power_law_r2"]))
            results.append(r)
        except Exception as ex:
            print("  NetworkX:  FAILED ({})".format(ex))

        # igraph
        try:
            r = run_igraph(n, e, 2.5)
            print("  igraph:    {:.3f}s  R2={:.3f}".format(r["time_sec"], r["power_law_r2"]))
            results.append(r)
        except Exception as ex:
            print("  igraph:    FAILED ({})".format(ex))

        # SAGA Mock（100K 以上跳过，太慢）
        if n <= 100000:
            try:
                r = run_saga_mock(n, e, 2.5)
                print("  SAGA-Mock: {:.3f}s  R2={:.3f}  edges={}  anomaly={}".format(
                    r["time_sec"], r["power_law_r2"], r["edges"], r["anomaly_rate_control"]))
                results.append(r)
            except Exception as ex:
                print("  SAGA-Mock: FAILED ({})".format(ex))

        # SAGA LLM（修复 #9: 小规模加 LLM 模式对比）
        # 只在 <=5000 节点时跑 LLM（大规模太慢）
        if n <= 5000:
            try:
                r = run_saga_llm(n, e, 2.5)
                print("  SAGA-LLM:  {:.3f}s  R2={:.3f}  edges={}  anomaly={}".format(
                    r["time_sec"], r["power_law_r2"], r["edges"], r["anomaly_rate_control"]))
                results.append(r)
            except Exception as ex:
                print("  SAGA-LLM:  FAILED ({})".format(ex))

    # 写 CSV
    csv_path = os.path.join(OUTPUT_DIR, "comparison.csv")
    if results:
        keys = list(results[0].keys())
        with open(csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(results)
        print("\n\nResults saved to: {}".format(csv_path))

    print("\nDone.")


if __name__ == "__main__":
    main()
