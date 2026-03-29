// ============================================================
// SAGA - 主应用组件
// 第 7 批 / 共 10 批
// 用途：全局状态管理（useReducer）、WebSocket 消息分发、
//       M3 Dark Theme 三栏布局（左配置 / 中图 / 右统计 + 底日志）
// Pipeline 阶段：贯穿所有阶段的前端状态中枢
// ============================================================

import React, { useReducer, useCallback, useRef, useMemo, useState } from 'react';
import { Box, AppBar, Toolbar, Typography, Chip, Snackbar, Alert } from '@mui/material';
import CircleIcon from '@mui/icons-material/Circle';
import useWebSocket from './hooks/useWebSocket';
import { formatNumber, formatDuration, formatSpeed, phaseName } from './utils/formatters';
// 第 8 批组件
import StatusBar from './components/StatusBar';
import ConfigPanel from './components/ConfigPanel';
// 第 9 批组件
import GraphCanvas from './components/GraphCanvas';
import StatsPanel from './components/StatsPanel';
import EventLog from './components/EventLog';
import NodeDetail from './components/NodeDetail';
// 第 10 批组件
import ExportToolbar from './components/ExportToolbar';
import CompletionCard from './components/CompletionCard';
// 回放组件
import ReplayControls from './components/ReplayControls';

// HTTP 基础地址（从环境变量读取，不硬编码）
const HTTP_URL = import.meta.env.VITE_HTTP_URL || 'http://localhost:8080';

// ============================================================
// 全局状态定义（useReducer）
// ============================================================

const initialState = {
  // --- Pipeline 状态 ---
  pipelineState: 'idle', // idle / running / paused / stopped / completed / error

  // --- 连接 ---
  connectionState: 'disconnected', // connected / disconnected / reconnecting
  reconnectCountdown: 0,

  // --- 配置 ---
  config: {},              // 当前运行配置（服务器返回的完整配置）
  serverConfig: {},        // 服务器默认配置（connected 时收到）

  // --- Phase 1 数据 ---
  nodes: [],               // 节点 ID 列表
  macroEdges: [],          // 宏观边列表
  degreeMap: {},           // 节点度数映射
  skeletonMeta: {},        // 骨架元数据

  // --- Phase 2 数据 ---
  dispatchStats: {},       // 调度统计

  // --- Phase 3 数据 ---
  microEdges: [],          // 微观边（限制最大条数防内存溢出）
  injectionStats: {},      // 注入统计

  // --- Phase 4 数据 ---
  settledEdges: [],        // 已结算边（限制最大条数）
  nodeStates: {},          // 所有节点当前状态
  anomalies: [],           // 异常事件列表

  // --- 进度 ---
  progress: {
    current_phase: 0,
    current_edge_index: 0,
    total_expected_edges: 0,
    phase_progress_percent: 0,
    overall_progress_percent: 0,
    current_time_block: '',
    elapsed_seconds: 0,
  },
  currentPhase: 0,

  // --- 统计 ---
  statistics: {},
  finalGraph: null,        // pipeline_complete 时的最终图数据

  // --- 场景和参数 ---
  scenario: '',
  inferredParams: [],      // LLM 推断的参数列表
  ragPreview: null,

  // --- 事件日志（前端维护，限制条数）---
  eventLog: [],            // [{ time, level, message, data }]

  // --- UI 状态 ---
  error: null,
  speed: 0,
  startTime: null,
  selectedNodeId: null,
  completionDismissed: false,

  // --- 回放状态 ---
  replayMode: false,       // 是否在回放中
  replayIndex: 0,          // 当前回放到第几条边
  replaySpeed: 1,          // 回放倍速 1x/2x/5x/10x
};

// 事件日志和边列表的最大条数（防内存溢出）
// 来自原型机经验：长时间运行不限制会爆内存
const MAX_EVENT_LOG = 500;
const MAX_EDGES_DISPLAY = 10000;

function reducer(state, action) {
  switch (action.type) {
    // --- 连接状态 ---
    case 'SET_CONNECTION':
      return { ...state, connectionState: action.payload };
    case 'SET_RECONNECT_COUNTDOWN':
      return { ...state, reconnectCountdown: action.payload };

    // --- 服务器消息分发 ---
    case 'WS_CONNECTED':
      return {
        ...state,
        connectionState: 'connected',
        serverConfig: action.payload.config || {},
      };

    case 'WS_STATUS':
      return {
        ...state,
        pipelineState: action.payload.status || state.pipelineState,
        config: action.payload.config || state.config,
      };

    case 'WS_PHASE_START':
      return {
        ...state,
        currentPhase: action.payload.phase,
        eventLog: _appendLog(state.eventLog, 'phase',
          `Phase ${action.payload.phase}: ${action.payload.name} started`),
      };

    case 'WS_SKELETON_COMPLETE': {
      const d = action.payload;
      return {
        ...state,
        nodes: d.nodes || [],
        macroEdges: d.macro_edges || [],
        degreeMap: d.degree_map || {},
        skeletonMeta: d.metadata || {},
        eventLog: _appendLog(state.eventLog, 'success',
          `Skeleton: ${(d.nodes || []).length} nodes, ${(d.macro_edges || []).length} edges`),
      };
    }

    case 'WS_TASKS_COMPLETE':
      return {
        ...state,
        dispatchStats: action.payload.stats || {},
        eventLog: _appendLog(state.eventLog, 'success',
          `Dispatch: ${(action.payload.stats || {}).total_tasks || 0} tasks`),
      };

    case 'WS_MICRO_EDGE_BATCH': {
      const batch = action.payload.edges || [];
      // 限制总数防内存溢出
      const combined = [...state.microEdges, ...batch].slice(-MAX_EDGES_DISPLAY);
      return {
        ...state,
        microEdges: combined,
        progress: action.payload._progress || state.progress,
      };
    }

    case 'WS_INJECTION_COMPLETE':
      return {
        ...state,
        injectionStats: action.payload.stats || {},
        eventLog: _appendLog(state.eventLog, 'success',
          `Injection: ${action.payload.total_edges || 0} micro edges`),
      };

    case 'WS_SETTLED_EDGE_BATCH': {
      const batch = action.payload.edges || [];
      const newEdges = batch.map(b => b.edge);
      const combined = [...state.settledEdges, ...newEdges].slice(-MAX_EDGES_DISPLAY);

      // 合并节点状态
      let updatedNodeStates = { ...state.nodeStates };
      for (const b of batch) {
        if (b.node_states) {
          Object.assign(updatedNodeStates, b.node_states);
        }
      }

      return {
        ...state,
        settledEdges: combined,
        nodeStates: updatedNodeStates,
        progress: action.payload._progress || state.progress,
      };
    }

    case 'WS_ANOMALY_DETECTED':
      return {
        ...state,
        anomalies: [...state.anomalies, action.payload].slice(-MAX_EVENT_LOG),
        eventLog: _appendLog(state.eventLog, 'error',
          `Anomaly: ${action.payload.u}→${action.payload.v} $${action.payload.amt} [${action.payload.tag}]`),
      };

    case 'WS_PROGRESS':
      return {
        ...state,
        progress: action.payload._progress || state.progress,
      };

    case 'WS_PIPELINE_COMPLETE': {
      const d = action.payload;
      return {
        ...state,
        pipelineState: d.partial ? 'stopped' : 'completed',
        finalGraph: d.final_graph || null,
        statistics: d.final_graph?.statistics || {},
        progress: {
          ...state.progress,
          overall_progress_percent: 100,
          elapsed_seconds: d.elapsed_seconds || 0,
        },
        eventLog: _appendLog(state.eventLog, 'success',
          `Pipeline ${d.partial ? 'stopped' : 'completed'}: ${d.elapsed_seconds?.toFixed(1)}s`),
      };
    }

    case 'WS_ERROR':
      return {
        ...state,
        pipelineState: 'error',
        error: action.payload.message || 'Unknown error',
        eventLog: _appendLog(state.eventLog, 'error',
          `Error: ${action.payload.message || 'Unknown'}`),
      };

    // --- 参数推断 ---
    case 'WS_INFERRED_PARAMETERS':
      return {
        ...state,
        inferredParams: action.payload.parameters || [],
        scenario: action.payload.scenario || state.scenario,
      };

    case 'WS_RAG_PREVIEW':
      return { ...state, ragPreview: action.payload };

    case 'WS_DEGREE_DIST_PREVIEW':
      return { ...state, degreePreview: action.payload };

    case 'WS_NODE_DETAIL':
      return { ...state, nodeDetail: action.payload };

    case 'WS_EVENT_INJECTED':
      return {
        ...state,
        eventLog: _appendLog(state.eventLog, 'phase',
          `Event injected: ${action.payload.event_id} [${action.payload.scope}]`),
      };

    // --- 前端本地状态 ---
    case 'SET_SCENARIO':
      return { ...state, scenario: action.payload };

    case 'SET_CONFIG':
      return { ...state, config: { ...state.config, ...action.payload } };

    case 'SET_PIPELINE_STATE':
      return { ...state, pipelineState: action.payload };

    case 'START_PIPELINE':
      return {
        ...state,
        pipelineState: 'running',
        startTime: Date.now(),
        // 重置数据
        microEdges: [],
        settledEdges: [],
        nodeStates: {},
        anomalies: [],
        statistics: {},
        finalGraph: null,
        error: null,
        progress: { ...initialState.progress },
        completionDismissed: false, // 重置完成弹窗状态
      };

    case 'DISMISS_COMPLETION':
      return { ...state, completionDismissed: true };

    case 'CLEAR_ERROR':
      return { ...state, error: null };

    case 'UPDATE_SPEED':
      return { ...state, speed: action.payload };

    case 'APPEND_EVENT_LOG':
      return {
        ...state,
        eventLog: _appendLog(state.eventLog, action.payload.level, action.payload.message),
      };

    case 'SET_SELECTED_NODE':
      return {
        ...state,
        selectedNodeId: action.payload,
        nodeDetail: action.payload ? state.nodeDetail : null, // 关闭时清空详情
      };

    case 'CLEAR_EVENT_LOG':
      return { ...state, eventLog: [] };

    // --- 回放控制 ---
    case 'REPLAY_START':
      return { ...state, replayMode: true, replayIndex: 0 };
    case 'REPLAY_STOP':
      return { ...state, replayMode: false };
    case 'REPLAY_SET_INDEX':
      return { ...state, replayIndex: action.payload };
    case 'REPLAY_SET_SPEED':
      return { ...state, replaySpeed: action.payload };

    default:
      return state;
  }
}

// 追加事件日志（限制条数）
function _appendLog(log, level, message) {
  const entry = {
    time: new Date().toLocaleTimeString(),
    level,  // 'phase' | 'success' | 'error' | 'info' | 'warning'
    message,
  };
  return [...log, entry].slice(-MAX_EVENT_LOG);
}


// ============================================================
// App 主组件
// ============================================================

export default function App() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const speedRef = useRef({ lastCount: 0, lastTime: Date.now() });

  // --- WebSocket 消息处理 ---
  const handleMessage = useCallback((data) => {
    const { type, data: payload } = data;

    // 消息类型→action 映射
    const typeMap = {
      'connected':            'WS_CONNECTED',
      'status':               'WS_STATUS',
      'phase_start':          'WS_PHASE_START',
      'skeleton_complete':    'WS_SKELETON_COMPLETE',
      'tasks_complete':       'WS_TASKS_COMPLETE',
      'micro_edge_batch':     'WS_MICRO_EDGE_BATCH',
      'injection_complete':   'WS_INJECTION_COMPLETE',
      'settled_edge_batch':   'WS_SETTLED_EDGE_BATCH',
      'anomaly_detected':     'WS_ANOMALY_DETECTED',
      'progress':             'WS_PROGRESS',
      'pipeline_complete':    'WS_PIPELINE_COMPLETE',
      'error':                'WS_ERROR',
      'inferred_parameters':  'WS_INFERRED_PARAMETERS',
      'rag_preview':          'WS_RAG_PREVIEW',
      'degree_dist_preview':  'WS_DEGREE_DIST_PREVIEW',
      'node_detail':          'WS_NODE_DETAIL',
      'event_injected':       'WS_EVENT_INJECTED',
    };

    const actionType = typeMap[type];
    if (actionType) {
      dispatch({ type: actionType, payload: payload || {} });
    }

    // 速度计算（每收到进度消息时更新）
    if (payload?._progress) {
      const now = Date.now();
      const elapsed = (now - speedRef.current.lastTime) / 1000;
      if (elapsed >= 1) { // 每秒更新一次
        const edgeDelta = (payload._progress.current_edge_index || 0) - speedRef.current.lastCount;
        const speed = edgeDelta / elapsed;
        dispatch({ type: 'UPDATE_SPEED', payload: Math.max(0, speed) });
        speedRef.current = { lastCount: payload._progress.current_edge_index || 0, lastTime: now };
      }
    }
  }, []);

  const { connectionState, send, reconnectCountdown } = useWebSocket(handleMessage);

  // 同步连接状态到 reducer
  React.useEffect(() => {
    dispatch({ type: 'SET_CONNECTION', payload: connectionState });
    if (connectionState === 'reconnecting') {
      dispatch({ type: 'SET_RECONNECT_COUNTDOWN', payload: reconnectCountdown });
    }
  }, [connectionState, reconnectCountdown]);

  // --- 是否锁定配置（运行中锁定）---
  const configLocked = ['running', 'paused'].includes(state.pipelineState);

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>

      {/* ===== 顶部状态栏 ===== */}
      <StatusBar
        connectionState={connectionState}
        reconnectCountdown={reconnectCountdown}
        pipelineState={state.pipelineState}
        currentPhase={state.currentPhase}
        progress={state.progress}
        speed={state.speed}
      />

      {/* ===== 中间主体：左配置 + 中图 + 右统计 ===== */}
      <Box sx={{ display: 'flex', flex: 1, overflow: 'hidden' }}>

        {/* 左侧配置栏 */}
        <Box sx={{
          width: 280,
          borderRight: 1,
          borderColor: 'divider',
          overflow: 'auto',
          p: 1.5,
        }}>
          <ConfigPanel state={state} dispatch={dispatch} send={send} />
        </Box>

        {/* 中央图画布 + 回放条 */}
        <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
          <Box sx={{ flex: 1, position: 'relative', bgcolor: 'background.default' }}>
            <GraphCanvas
              nodes={state.nodes}
              macroEdges={state.macroEdges}
              settledEdges={
                state.replayMode
                  ? state.settledEdges.slice(0, state.replayIndex)
                  : state.settledEdges
              }
              degreeMap={state.degreeMap}
              nodeStates={state.nodeStates}
              onNodeClick={(nodeId) => {
                dispatch({ type: 'SET_SELECTED_NODE', payload: nodeId });
                send({ type: 'get_node_detail', node_id: nodeId });
              }}
              pipelineState={state.pipelineState}
            />
          </Box>
          {/* 回放控制条（Pipeline 完成后显示）*/}
          <ReplayControls
            totalEdges={state.settledEdges.length}
            replayIndex={state.replayIndex}
            replaySpeed={state.replaySpeed}
            replayMode={state.replayMode}
            onStart={() => dispatch({ type: 'REPLAY_START' })}
            onStop={() => dispatch({ type: 'REPLAY_STOP' })}
            onSetIndex={(idx) => dispatch({ type: 'REPLAY_SET_INDEX', payload: typeof idx === 'function' ? idx(state.replayIndex) : idx })}
            onSetSpeed={(s) => dispatch({ type: 'REPLAY_SET_SPEED', payload: s })}
            pipelineState={state.pipelineState}
          />
        </Box>

        {/* 右侧统计栏 */}
        <Box sx={{
          width: 300,
          borderLeft: 1,
          borderColor: 'divider',
          overflow: 'auto',
          p: 1.5,
        }}>
          <StatsPanel
            nodes={state.nodes}
            macroEdges={state.macroEdges}
            settledEdges={state.settledEdges}
            anomalies={state.anomalies}
            nodeStates={state.nodeStates}
            statistics={state.statistics}
            degreeMap={state.degreeMap}
            pipelineState={state.pipelineState}
          />
        </Box>

      </Box>

      {/* ===== 底部：事件日志 + 导出 ===== */}
      <Box sx={{
        height: 180,
        borderTop: 1,
        borderColor: 'divider',
        display: 'flex',
        overflow: 'hidden',
      }}>
        {/* 事件日志 — 左半 */}
        <Box sx={{ flex: 1, overflow: 'hidden' }}>
          <EventLog
            eventLog={state.eventLog}
            onClear={() => dispatch({ type: 'CLEAR_EVENT_LOG' })}
          />
        </Box>

        {/* 导出工具栏 — 右半 */}
        <Box sx={{
          flex: 1,
          borderLeft: 1,
          borderColor: 'divider',
          p: 1.5,
        }}>
          <ExportToolbar
            pipelineState={state.pipelineState}
            outputFormats={state.config.output_formats || ['json', 'csv']}
            hasData={state.settledEdges.length > 0 || state.nodes.length > 0}
          />
        </Box>
      </Box>

      {/* ===== 节点详情 Drawer ===== */}
      <NodeDetail
        open={!!state.selectedNodeId}
        onClose={() => dispatch({ type: 'SET_SELECTED_NODE', payload: null })}
        nodeDetail={state.nodeDetail}
        nodeStates={state.nodeStates}
        selectedNodeId={state.selectedNodeId}
        settledEdges={state.settledEdges}
      />

      {/* ===== 完成总结卡片 ===== */}
      <CompletionCard
        open={
          !state.completionDismissed &&
          (state.pipelineState === 'completed' ||
           (state.pipelineState === 'stopped' && state.settledEdges.length > 0))
        }
        onClose={() => dispatch({ type: 'DISMISS_COMPLETION' })}
        statistics={state.statistics}
        elapsed={state.progress.elapsed_seconds || 0}
        totalNodes={state.nodes.length}
        partial={state.pipelineState === 'stopped'}
        outputFormats={state.config.output_formats || ['json', 'csv']}
      />

      {/* ===== 错误 Snackbar ===== */}
      <Snackbar
        open={!!state.error}
        autoHideDuration={8000}
        onClose={() => dispatch({ type: 'CLEAR_ERROR' })}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert
          severity="error"
          variant="filled"
          onClose={() => dispatch({ type: 'CLEAR_ERROR' })}
        >
          {state.error}
        </Alert>
      </Snackbar>
    </Box>
  );
}
