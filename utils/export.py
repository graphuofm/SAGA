# ============================================================
# SAGA - 多格式导出工具
# 第 6 批 / 共 10 批
# 用途：将 Phase 4 最终图数据导出为 JSON / CSV / GraphML /
#       EdgeList / AdjList 等格式，支持按用户勾选的属性过滤列，
#       打包为 ZIP 供前端下载
# Pipeline 阶段：完成阶段（导出）
# ============================================================

import csv
import io
import os
import zipfile
from collections import defaultdict
from typing import Dict, Any, List, Optional

from config import OUTPUT_DIR
from utils.logger import get_logger, get_event_log, get_agent_traces

logger = get_logger("saga.utils.export")

# orjson 加速 JSON 序列化
try:
    import orjson
    def _json_dumps(obj, indent=False):
        # type: (Any, bool) -> bytes
        opt = orjson.OPT_INDENT_2 if indent else 0
        return orjson.dumps(obj, option=opt)
    def _json_dumps_str(obj, indent=False):
        # type: (Any, bool) -> str
        return _json_dumps(obj, indent).decode("utf-8")
except ImportError:
    import json
    def _json_dumps(obj, indent=False):
        # type: (Any, bool) -> bytes
        s = json.dumps(obj, ensure_ascii=False, default=str,
                       indent=2 if indent else None)
        return s.encode("utf-8")
    def _json_dumps_str(obj, indent=False):
        # type: (Any, bool) -> str
        return json.dumps(obj, ensure_ascii=False, default=str,
                          indent=2 if indent else None)


# ============================================================
# 属性过滤辅助函数
# ============================================================

def _filter_dict(d, allowed_keys):
    # type: (Dict, Optional[List[str]]) -> Dict
    """保留字典中 allowed_keys 指定的字段，None 表示不过滤"""
    if allowed_keys is None:
        return d
    return {k: v for k, v in d.items() if k in allowed_keys}


# 节点的所有可选属性
NODE_PROPERTIES = ["id", "final_balance", "risk_level", "status",
                   "transaction_count", "anomaly_count"]

# 边的所有可选属性
EDGE_PROPERTIES = ["time", "u", "v", "amt", "tag", "anomaly_reason",
                   "status", "properties"]


# ============================================================
# 单格式导出函数
# ============================================================

def to_json(final_graph, selected_properties=None):
    # type: (Dict[str, Any], Optional[List[str]]) -> bytes
    """
    导出为 JSON 格式

    输入：
      final_graph: GraphStateMachine.get_final_graph() 返回的字典
      selected_properties: 用户勾选的属性列表（None=全部）
    输出：
      JSON bytes
    """
    nodes = final_graph.get("nodes", [])
    edges = final_graph.get("edges", [])
    stats = final_graph.get("statistics", {})

    # 过滤节点属性
    filtered_nodes = [_filter_dict(n, selected_properties) for n in nodes]
    # 过滤边属性
    filtered_edges = [_filter_dict(e, selected_properties) for e in edges]

    output = {
        "nodes": filtered_nodes,
        "edges": filtered_edges,
        "statistics": stats,
    }
    return _json_dumps(output, indent=True)


def to_csv(final_graph, selected_properties=None, user_params=None):
    # type: (Dict[str, Any], Optional[List[str]], Optional[Dict]) -> Dict[str, bytes]
    """
    导出为单个 saga_output.csv
    每行一条边，用户参数展平为列，pd.read_csv() 直接用
    """
    nodes = final_graph.get("nodes", [])
    edges = final_graph.get("edges", [])
    params = user_params or {}

    # 节点查找表
    node_map = {}
    for n in nodes:
        node_map[n.get("id", "")] = n

    # 构建列名：核心列 + 用户参数列
    core_cols = ["time", "source", "target", "amount", "tag", "anomaly_type",
                 "risk_score", "transaction_type", "source_risk", "target_risk"]
    # 用户参数列名清洗（空格→下划线，小写）
    param_cols = []
    param_values = {}
    for k, v in params.items():
        col_name = str(k).strip().replace(" ", "_").lower()
        param_cols.append(col_name)
        param_values[col_name] = v

    all_cols = core_cols + param_cols

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=all_cols, extrasaction="ignore")
    writer.writeheader()

    for e in edges:
        src_id = e.get("u", "")
        tgt_id = e.get("v", "")
        src_node = node_map.get(src_id, {})
        tgt_node = node_map.get(tgt_id, {})
        props = e.get("properties", {})

        row = {
            "time": e.get("time", ""),
            "source": src_id,
            "target": tgt_id,
            "amount": e.get("amt", 0),
            "tag": e.get("tag", "normal"),
            "anomaly_type": e.get("anomaly_reason", ""),
            "risk_score": props.get("risk_score", 0),
            "transaction_type": props.get("transaction_type", ""),
            "source_risk": src_node.get("risk_level", ""),
            "target_risk": tgt_node.get("risk_level", ""),
        }
        # 展平用户参数到每行
        row.update(param_values)
        writer.writerow(row)

    return {
        "saga_output.csv": buf.getvalue().encode("utf-8"),
    }


def generate_meta_json(final_graph, pipeline_config=None, user_params=None):
    # type: (Dict[str, Any], Optional[Dict], Optional[Dict]) -> bytes
    """
    生成 saga_meta.json — 记录所有生成参数和统计结果
    GNN 研究者用这个知道数据是怎么生成的
    """
    meta = {
        "generation_config": {},
        "user_parameters": user_params or {},
        "statistics": final_graph.get("statistics", {}),
    }

    if pipeline_config:
        meta["generation_config"] = {
            "nodes": pipeline_config.get("num_nodes"),
            "edges": pipeline_config.get("num_edges"),
            "days": pipeline_config.get("time_span_value"),
            "gamma": pipeline_config.get("gamma"),
            "anomaly_rate": pipeline_config.get("anomaly_rate"),
            "domain": pipeline_config.get("scenario", pipeline_config.get("domain")),
            "rag_level": pipeline_config.get("rag_level", "full"),
            "llm_backend": pipeline_config.get("llm_backend", ""),
            "macro_block_unit": pipeline_config.get("macro_block_unit"),
            "micro_granularity": pipeline_config.get("micro_granularity"),
        }

    return _json_dumps(meta, indent=True)


def to_graphml(final_graph, selected_properties=None):
    # type: (Dict[str, Any], Optional[List[str]]) -> bytes
    """
    导出为 GraphML 格式（XML，Neo4j / igraph / Gephi 可直接导入）
    """
    nodes = final_graph.get("nodes", [])
    edges = final_graph.get("edges", [])

    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append('<graphml xmlns="http://graphml.graphstruct.org/graphml">')

    # 属性定义
    # 节点属性
    node_attrs = ["final_balance", "risk_level", "status",
                  "transaction_count", "anomaly_count"]
    for attr in node_attrs:
        atype = "double" if attr in ("final_balance",) else "string"
        if attr in ("transaction_count", "anomaly_count"):
            atype = "int"
        lines.append('  <key id="{a}" for="node" attr.name="{a}" attr.type="{t}"/>'.format(
            a=attr, t=atype))

    # 边属性
    edge_attrs = ["time", "amt", "tag", "anomaly_reason", "status"]
    for attr in edge_attrs:
        atype = "int" if attr == "amt" else "string"
        lines.append('  <key id="{a}" for="edge" attr.name="{a}" attr.type="{t}"/>'.format(
            a=attr, t=atype))

    lines.append('  <graph id="saga" edgedefault="directed">')

    # 节点
    for node in nodes:
        nid = node.get("id", "")
        lines.append('    <node id="{nid}">'.format(nid=nid))
        for attr in node_attrs:
            if attr in node:
                val = node[attr]
                lines.append('      <data key="{a}">{v}</data>'.format(a=attr, v=val))
        lines.append('    </node>')

    # 边
    for idx, edge in enumerate(edges):
        src = edge.get("u", "")
        tgt = edge.get("v", "")
        lines.append('    <edge id="e{i}" source="{s}" target="{t}">'.format(
            i=idx, s=src, t=tgt))
        for attr in edge_attrs:
            if attr in edge:
                val = edge[attr]
                lines.append('      <data key="{a}">{v}</data>'.format(a=attr, v=val))
        lines.append('    </edge>')

    lines.append('  </graph>')
    lines.append('</graphml>')

    return "\n".join(lines).encode("utf-8")


def to_edgelist(final_graph):
    # type: (Dict[str, Any]) -> bytes
    """
    导出为 EdgeList 格式（每行: source target weight）
    """
    edges = final_graph.get("edges", [])
    lines = []
    for e in edges:
        lines.append("{u} {v} {w}".format(
            u=e.get("u", ""), v=e.get("v", ""), w=e.get("amt", 0)))
    return "\n".join(lines).encode("utf-8")


def to_adjlist(final_graph):
    # type: (Dict[str, Any]) -> bytes
    """
    导出为 Adjacency List 格式（每行: node neighbor1 neighbor2 ...）
    """
    edges = final_graph.get("edges", [])
    adj = defaultdict(set)  # type: Dict[str, set]
    for e in edges:
        u = e.get("u", "")
        v = e.get("v", "")
        if u and v:
            adj[u].add(v)

    lines = []
    for node in sorted(adj.keys()):
        neighbors = " ".join(sorted(adj[node]))
        lines.append("{n} {nb}".format(n=node, nb=neighbors))
    return "\n".join(lines).encode("utf-8")


# ============================================================
# 运行日志导出
# ============================================================

def generate_log_json(pipeline_config):
    # type: (Dict[str, Any]) -> bytes
    """
    生成完整运行日志 JSON

    输入：pipeline_config 本次运行的配置快照
    输出：JSON bytes，包含 pipeline_config + timeline + agent_traces
    """
    log_data = {
        "pipeline_config": pipeline_config,
        "timeline": get_event_log(),
        "agent_traces": get_agent_traces(),
    }
    return _json_dumps(log_data, indent=True)


# ============================================================
# ZIP 打包
# ============================================================

def package_zip(final_graph, formats, selected_properties=None,
                pipeline_config=None):
    # type: (Dict[str, Any], List[str], Optional[List[str]], Optional[Dict]) -> bytes
    """打包为 ZIP：saga_output.csv + saga_meta.json + 可选其他格式"""
    buf = io.BytesIO()
    user_params = (pipeline_config or {}).get("user_params", {})

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # 始终输出核心文件
        user_params = (pipeline_config or {}).get("user_params", {})
        csv_files = to_csv(final_graph, user_params=user_params)
        for fname, fdata in csv_files.items():
            zf.writestr("saga_output/{f}".format(f=fname), fdata)

        # saga_meta.json（包含生成参数 + 统计）
        meta = generate_meta_json(final_graph, pipeline_config, user_params)
        zf.writestr("saga_output/saga_meta.json", meta)

        # 可选格式
        for fmt in formats:
            if fmt == "json":
                data = to_json(final_graph, selected_properties)
                zf.writestr("saga_output/final_graph.json", data)
            elif fmt == "graphml":
                data = to_graphml(final_graph, selected_properties)
                zf.writestr("saga_output/graph.graphml", data)
            elif fmt == "edgelist":
                data = to_edgelist(final_graph)
                zf.writestr("saga_output/graph.edgelist", data)
            elif fmt == "adjlist":
                data = to_adjlist(final_graph)
                zf.writestr("saga_output/graph.adjlist", data)

        # 运行日志
        if pipeline_config:
            log_data = generate_log_json(pipeline_config)
            zf.writestr("saga_output/run_log.json", log_data)

    return buf.getvalue()
