#!/usr/bin/env python3
# ============================================================
# SAGA CLI - 命令行入口
# 用途：在服务器/集群上批量生成时序图数据
#       直接调用 core/ 内核模块，不需要 WebSocket/浏览器
#       支持 YAML 批量配置和自动统计计算
# 使用：python saga_cli.py --nodes 5000 --days 60 --domain finance --output ./results
# ============================================================

import argparse
import asyncio
import csv
import json
import os
import random
import sys
import time
from datetime import datetime
from typing import Dict, Any, List, Optional

import numpy as np

# 确保项目根目录在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    LLM_BACKEND, OLLAMA_BASE_URL, OLLAMA_MODEL,
    OPENAI_BASE_URL, OPENAI_MODEL,
)
from core.pipeline import SAGAPipeline
from utils.stats import compute_statistics
from utils.logger import get_logger

logger = get_logger("saga.cli")

# orjson 加速（OPT_SERIALIZE_NUMPY 处理 numpy 类型）
try:
    import orjson
    def _json_dump(obj, path):
        with open(path, "wb") as f:
            f.write(orjson.dumps(obj, option=orjson.OPT_INDENT_2 | orjson.OPT_SERIALIZE_NUMPY))
except ImportError:
    def _json_dump(obj, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2, default=str)


# ============================================================
# LLM 可达性检查
# ============================================================

def check_llm_health(provider, endpoint):
    # type: (str, str) -> bool
    """检查 LLM 服务是否可达，不可达则打印错误并返回 False"""
    import urllib.request
    import urllib.error

    if provider == "mock":
        return True

    try:
        if provider == "ollama":
            url = "{base}/api/tags".format(base=endpoint.rstrip("/"))
        else:
            url = "{base}/v1/models".format(base=endpoint.rstrip("/"))

        req = urllib.request.Request(url, method="GET")
        resp = urllib.request.urlopen(req, timeout=10)
        if resp.status == 200:
            print("  LLM service OK: {p} @ {u}".format(p=provider, u=endpoint))
            return True
    except Exception as e:
        pass

    print("[ERROR] LLM service unreachable: {p} @ {u}".format(p=provider, u=endpoint))
    print("  Please start the LLM service or use --mode mock for debugging.")
    return False


# ============================================================
# 终端事件回调（CLI 进度输出）
# ============================================================

def make_cli_callback(quiet=False, verbose=False):
    # type: (bool, bool) -> callable
    """创建 CLI 版的事件回调函数"""
    _tqdm_bar = [None]  # 用 list 包装以在闭包中修改

    def callback(event_type, data):
        if quiet:
            return

        if event_type == "phase_start":
            phase = data.get("phase", 0)
            name = data.get("name", "")
            print("[Phase {p}] {n}...".format(p=phase, n=name))

        elif event_type == "skeleton_complete":
            print("  \u2713 {n:,} nodes, {e:,} macro edges, {b} time blocks ({t})".format(
                n=data.get("nodes", 0),
                e=data.get("edges", 0),
                b=data.get("time_blocks", 0),
                t=_fmt_ms(0),  # Phase S 极快
            ))

        elif event_type == "dispatch_complete":
            print("  \u2713 {t:,} tasks".format(t=data.get("tasks", 0)))

        elif event_type == "injection_complete":
            print("  \u2713 {e:,} micro edges".format(e=data.get("micro_edges", 0)))
            # 关闭 tqdm（如果有）
            if _tqdm_bar[0]:
                _tqdm_bar[0].close()
                _tqdm_bar[0] = None

        elif event_type == "pipeline_complete":
            total = data.get("total_edges", 0)
            anom = data.get("anomaly_edges", 0)
            sec = data.get("elapsed_sec", 0)
            rate = anom / max(total, 1) * 100
            print("  \u2713 {n:,} normal / {a:,} anomaly ({r:.1f}%)".format(
                n=total - anom, a=anom, r=rate))

    return callback


def _fmt_ms(ms):
    # type: (float) -> str
    if ms < 1000:
        return "{:.1f}ms".format(ms)
    return "{:.1f}s".format(ms / 1000)


# ============================================================
# 单次运行
# ============================================================

def run_single(config, output_dir, formats, no_stats=False, quiet=False, verbose=False):
    # type: (Dict, str, List[str], bool, bool, bool) -> Dict[str, Any]
    """执行单次 pipeline 并输出结果"""
    os.makedirs(output_dir, exist_ok=True)

    # 保存配置快照
    config_snapshot = dict(config)
    _save_yaml(config_snapshot, os.path.join(output_dir, "config_used.yaml"))

    # 运行 Pipeline
    callback = make_cli_callback(quiet, verbose)
    pipeline = SAGAPipeline(config, on_event=callback)
    result = asyncio.run(pipeline.run())

    # 导出结果文件
    _export_results(result, output_dir, formats, user_params=config.get("user_params"))

    # 计算统计
    stats = {}
    if not no_stats:
        stats = compute_statistics(
            result,
            timings=pipeline.timings,
            config=config,
        )
        _json_dump(stats, os.path.join(output_dir, "stats.json"))

    # 保存 pipeline 日志
    from utils.logger import get_event_log
    _json_dump(get_event_log(), os.path.join(output_dir, "pipeline_log.json"))

    # 打印摘要
    if not quiet:
        _print_summary(stats, output_dir, pipeline.timings)

    return stats


def _export_results(result, output_dir, formats, user_params=None):
    # type: (Dict, str, List[str], Optional[Dict]) -> None
    """导出结果到多种格式"""
    from utils.export import to_json, to_csv, to_graphml, to_edgelist, to_adjlist

    final_graph = {
        "nodes": result.get("nodes", []),
        "edges": result.get("edges", []),
        "statistics": result.get("statistics", {}),
    }

    for fmt in formats:
        if fmt == "json":
            data = to_json(final_graph)
            with open(os.path.join(output_dir, "final_graph.json"), "wb") as f:
                f.write(data)
        elif fmt == "csv":
            csv_files = to_csv(final_graph, user_params=user_params)
            for fname, fdata in csv_files.items():
                with open(os.path.join(output_dir, fname), "wb") as f:
                    f.write(fdata)
        elif fmt == "graphml":
            data = to_graphml(final_graph)
            with open(os.path.join(output_dir, "graph.graphml"), "wb") as f:
                f.write(data)
        elif fmt == "edgelist":
            data = to_edgelist(final_graph)
            with open(os.path.join(output_dir, "graph.edgelist"), "wb") as f:
                f.write(data)
        elif fmt == "adjlist":
            data = to_adjlist(final_graph)
            with open(os.path.join(output_dir, "graph.adjlist"), "wb") as f:
                f.write(data)


def _print_summary(stats, output_dir, timings):
    # type: (Dict, str, Dict) -> None
    """打印终端摘要框"""
    total_sec = timings.get("total_ms", 0) / 1000
    nodes = stats.get("total_nodes", 0)
    edges = stats.get("total_edges", 0)
    anom_rate = stats.get("anomaly_rate", 0) * 100
    anom_count = stats.get("anomaly_count", 0)
    gamma = stats.get("power_law_gamma", 0)
    r2 = stats.get("power_law_r2", 0)

    print("")
    print("\u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500 SAGA Results \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510")
    print("\u2502  Elapsed:     {t:<25s}\u2502".format(t="{:.1f}s".format(total_sec)))
    print("\u2502  Nodes:       {n:<25s}\u2502".format(n="{:,}".format(nodes)))
    print("\u2502  Edges:       {e:<25s}\u2502".format(e="{:,}".format(edges)))
    print("\u2502  Anomaly:     {a:<25s}\u2502".format(
        a="{:.1f}% ({:,})".format(anom_rate, anom_count)))
    print("\u2502  Power-law:   {p:<25s}\u2502".format(
        p="\u03b3={:.2f}, R\u00b2={:.2f}".format(gamma, r2)))
    print("\u2502  Output:      {o:<25s}\u2502".format(o=output_dir[:25]))
    print("\u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518")


# ============================================================
# YAML 批量运行
# ============================================================

def run_from_yaml(yaml_path, quiet=False, verbose=False):
    # type: (str, bool, bool) -> None
    """从 YAML 配置文件执行单次或批量运行"""
    import yaml

    with open(yaml_path, "r") as f:
        spec = yaml.safe_load(f)

    defaults = spec.get("defaults", {})
    runs = spec.get("runs", [])
    output_base = spec.get("output_base", spec.get("output", "./output/yaml_run"))
    exp_name = spec.get("experiment_name", "experiment")

    if not runs:
        # 单次运行：整个 YAML 就是一个 config
        config = _build_config_from_yaml(spec, {})
        output_dir = output_base
        formats = spec.get("formats", ["json", "csv"])
        run_single(config, output_dir, formats, quiet=quiet, verbose=verbose)
        return

    # 批量运行
    print("=" * 50)
    print("Experiment: {name}  ({n} runs)".format(name=exp_name, n=len(runs)))
    print("=" * 50)

    summary_rows = []

    for idx, run_spec in enumerate(runs):
        run_name = run_spec.get("name", "run_{i}".format(i=idx))
        print("\n--- [{i}/{n}] {name} ---".format(i=idx + 1, n=len(runs), name=run_name))

        # 合并: defaults < run_spec
        merged = dict(defaults)
        merged.update(run_spec)
        config = _build_config_from_yaml(merged, defaults)
        output_dir = os.path.join(output_base, run_name)
        formats = merged.get("formats", defaults.get("formats", ["json", "csv"]))

        stats = run_single(config, output_dir, formats, quiet=quiet, verbose=verbose)

        # 收集 summary 行
        # 修复 #14: 区分用户设置的 gamma（input）和拟合出的 gamma（fitted）
        row = {"name": run_name}
        row["num_nodes"] = config.get("num_nodes")
        row["target_edges"] = config.get("num_edges")
        row["time_span_days"] = config.get("time_span_days")
        row["input_gamma"] = config.get("power_law_gamma")
        row["initial_balance"] = config.get("initial_balance")
        row["input_anomaly_rate"] = config.get("anomaly_rate")
        row.update({k: stats.get(k, "") for k in [
            "total_edges", "anomaly_rate", "fitted_gamma", "power_law_r2",
            "clustering_coefficient", "temporal_burstiness", "total_ms",
        ]})
        if stats.get("llm_provider"):
            row["llm_provider"] = stats["llm_provider"]
        if stats.get("llm_model"):
            row["llm_model"] = stats["llm_model"]
        summary_rows.append(row)

    # 写 summary.csv
    if summary_rows:
        csv_path = os.path.join(output_base, "summary.csv")
        os.makedirs(output_base, exist_ok=True)
        keys = list(summary_rows[0].keys())
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(summary_rows)
        print("\n\u2713 Summary saved: {p}".format(p=csv_path))


def _build_config_from_yaml(spec, defaults):
    # type: (Dict, Dict) -> Dict[str, Any]
    """从 YAML spec 构建 pipeline config 字典"""
    # 修复 #8/#21: edges 缺失时默认 nodes*5
    nodes = spec.get("nodes", defaults.get("nodes", 1000))
    edges = spec.get("edges", defaults.get("edges"))
    if edges is None:
        edges = nodes * 5
    return {
        "num_nodes": nodes,
        "num_edges": edges,
        "anomaly_rate": spec.get("anomaly_rate", defaults.get("anomaly_rate", 0.1)),
        "time_span_days": spec.get("days", defaults.get("days", 30)),
        "power_law_gamma": spec.get("gamma", defaults.get("gamma", 2.5)),
        "hub_ratio": spec.get("hub_ratio", defaults.get("hub_ratio", 0.1)),
        "macro_block_unit": spec.get("macro_block", defaults.get("macro_block", "day")),
        "micro_granularity": spec.get("micro_granularity", defaults.get("micro_granularity", "minute")),
        "domain": spec.get("domain", defaults.get("domain", "finance")),
        "rag_level": spec.get("rag_level", defaults.get("rag_level", "full")),
        "initial_balance": spec.get("initial_balance", defaults.get("initial_balance", 1000)),
        "llm_provider": spec.get("mode", LLM_BACKEND),
        "llm_concurrency": spec.get("concurrency", 100),
        "llm_temperature": spec.get("temperature", 0.7),
        "micro_edges_min": spec.get("micro_edges_min", 2),
        "micro_edges_max": spec.get("micro_edges_max", 3),
        "max_retries": spec.get("max_retries", 3),
        "risk_threshold_medium": spec.get("risk_threshold_medium", 1),
        "risk_threshold_high": spec.get("risk_threshold_high", 3),
        "freeze_threshold": spec.get("freeze_threshold", 5),
        "seed": spec.get("seed", defaults.get("seed")),
        "user_params": spec.get("user_params", {}),
        "skeleton_mode": spec.get("skeleton_mode", "power_law"),
        "injection_mode": spec.get("injection_mode", "llm"),
        "skip_alignment": spec.get("skip_alignment", False),
        "force_known_balance": spec.get("force_known_balance", False),
        "burstiness": spec.get("burstiness", defaults.get("burstiness", 0.3)),
        # LLM 端点（从 .env 或 YAML）
        "llm_endpoint": spec.get("llm_endpoint", OLLAMA_BASE_URL),
        "llm_model": spec.get("llm_model", OLLAMA_MODEL),
    }


def _save_yaml(data, path):
    # type: (Dict, str) -> None
    """保存字典为 YAML 文件"""
    try:
        import yaml
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
    except ImportError:
        # 没有 yaml 就存 JSON
        _json_dump(data, path.replace(".yaml", ".json"))


# ============================================================
# 命令行参数解析
# ============================================================

def parse_args():
    p = argparse.ArgumentParser(
        description="SAGA CLI — Temporal Graph Data Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  # Quick mock test
  python saga_cli.py --mode mock --nodes 100 --days 7 --output ./output/test

  # LLM mode with Ollama
  python saga_cli.py --nodes 5000 --days 60 --domain finance --output ./results/exp01

  # YAML batch experiment
  python saga_cli.py --config experiments/exp_scalability.yaml
""",
    )

    # 图结构
    g = p.add_argument_group("Graph Structure")
    g.add_argument("--nodes", type=int, default=1000, help="Number of nodes (default: 1000)")
    g.add_argument("--edges", type=int, default=None, help="Number of edges (default: nodes*5)")
    g.add_argument("--days", type=int, default=30, help="Time span in days (default: 30)")
    g.add_argument("--gamma", type=float, default=2.5, help="Power-law exponent (default: 2.5)")
    g.add_argument("--anomaly-rate", type=float, default=0.1, help="Anomaly rate 0.0-0.5 (default: 0.1)")
    g.add_argument("--macro-block", default="day", choices=["hour", "day", "week", "month"])
    g.add_argument("--micro-gran", default="minute", choices=["second", "minute", "hour"])

    # 业务
    b = p.add_argument_group("Domain")
    b.add_argument("--domain", default="finance", choices=["finance", "network", "cyber", "traffic"])
    b.add_argument("--rag-level", default="full", choices=["basic", "full", "none"])
    b.add_argument("--initial-balance", type=int, default=1000)

    # LLM
    l = p.add_argument_group("LLM")
    l.add_argument("--mode", default=None, help="mock/ollama/openai/vllm (default: from .env)")
    l.add_argument("--llm-endpoint", default=None)
    l.add_argument("--llm-model", default=None)
    l.add_argument("--concurrency", type=int, default=100)
    l.add_argument("--temperature", type=float, default=0.7)

    # 输出
    o = p.add_argument_group("Output")
    o.add_argument("--output", default=None, help="Output directory")
    o.add_argument("--formats", default="json,csv", help="Comma-separated: json,csv,graphml,edgelist")

    # 实验
    e = p.add_argument_group("Experiment")
    e.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    e.add_argument("--config", default=None, help="YAML config file (overrides CLI args)")
    e.add_argument("--no-stats", action="store_true", help="Skip statistics computation")
    e.add_argument("--quiet", action="store_true")
    e.add_argument("--verbose", action="store_true")

    # 消融
    a = p.add_argument_group("Ablation")
    a.add_argument("--skeleton-mode", default="power_law", choices=["power_law", "random_er"])
    a.add_argument("--injection-mode", default="llm", choices=["llm", "random_attr"])
    a.add_argument("--skip-alignment", action="store_true")

    return p.parse_args()


# ============================================================
# Main
# ============================================================

def main():
    args = parse_args()

    # YAML 模式
    if args.config:
        if not os.path.exists(args.config):
            print("[ERROR] Config file not found: {f}".format(f=args.config))
            sys.exit(1)
        run_from_yaml(args.config, quiet=args.quiet, verbose=args.verbose)
        return

    # 确定 LLM provider
    provider = args.mode or LLM_BACKEND
    endpoint = args.llm_endpoint or OLLAMA_BASE_URL
    model = args.llm_model or OLLAMA_MODEL

    # LLM 可达性检查
    if not check_llm_health(provider, endpoint):
        sys.exit(1)

    # 输出目录
    output_dir = args.output
    if not output_dir:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = "./output/run_{ts}".format(ts=ts)

    # 组装 config
    # 修复: edges 默认 nodes*5, hub_ratio 之前引用了不存在的 args.hub_ratio
    num_edges = args.edges if args.edges else args.nodes * 5
    config = {
        "num_nodes": args.nodes,
        "num_edges": num_edges,
        "time_span_days": args.days,
        "power_law_gamma": args.gamma,
        "hub_ratio": 0.1,
        "macro_block_unit": args.macro_block,
        "micro_granularity": args.micro_gran,
        "domain": args.domain,
        "rag_level": args.rag_level,
        "initial_balance": args.initial_balance,
        "anomaly_rate": args.anomaly_rate,
        "llm_provider": provider,
        "llm_endpoint": endpoint,
        "llm_model": model,
        "llm_concurrency": args.concurrency,
        "llm_temperature": args.temperature,
        "micro_edges_min": 2,
        "micro_edges_max": 3,
        "max_retries": 3,
        "risk_threshold_medium": 1,
        "risk_threshold_high": 3,
        "freeze_threshold": 5,
        "seed": args.seed,
        "user_params": {},
        "skeleton_mode": args.skeleton_mode,
        "injection_mode": args.injection_mode,
        "skip_alignment": args.skip_alignment,
        "burstiness": 0.3,
    }

    formats = [f.strip() for f in args.formats.split(",")]

    if not args.quiet:
        print("SAGA CLI")
        print("  Nodes: {:,}  Edges: {:,}  Days: {}  Domain: {}".format(
            args.nodes, num_edges, args.days, args.domain))
        print("  LLM: {} ({})".format(provider, model))
        print("  Anomaly rate: {:.1f}%".format(args.anomaly_rate * 100))
        print("  Output: {}".format(output_dir))
        print("")

    run_single(config, output_dir, formats,
               no_stats=args.no_stats, quiet=args.quiet, verbose=args.verbose)


if __name__ == "__main__":
    main()
