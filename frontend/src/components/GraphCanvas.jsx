// ============================================================
// SAGA - 图画布组件（Sigma.js WebGL）— 更新版
// 边半透明 + 论文白色背景开关 + 悬停显示度数/边数
// ============================================================

import React, { useEffect, useRef, useState } from 'react';
import { Box, Typography, Chip, IconButton, Tooltip } from '@mui/material';
import LightModeIcon from '@mui/icons-material/LightMode';
import DarkModeIcon from '@mui/icons-material/DarkMode';
import Graph from 'graphology';

// 暗色模式颜色
const DARK = {
  bg: '#121212',
  default: '#9e9e9e',
  success: '#66bb6a',
  warning: '#ffa726',
  error: '#f44336',
  edgeNormal: 'rgba(255,255,255,0.06)',   // 极淡半透明
  edgeAnomaly: 'rgba(244,67,54,0.4)',      // 半透明红
};

// 论文白色模式颜色
const LIGHT = {
  bg: '#ffffff',
  default: '#bdbdbd',
  success: '#2e7d32',
  warning: '#e65100',
  error: '#c62828',
  edgeNormal: 'rgba(0,0,0,0.08)',
  edgeAnomaly: 'rgba(198,40,40,0.5)',
};

function riskColor(risk, colors) {
  if (risk === 'frozen') return colors.default;
  if (risk === 'high') return colors.error;
  if (risk === 'medium') return colors.warning;
  if (risk === 'low') return colors.success;
  return colors.default;
}

function degreeToSize(degree, maxDegree) {
  if (maxDegree <= 0) return 3;
  return 2 + Math.min(degree / maxDegree, 1) * 4;  // 2~6px，紧凑
}

export default function GraphCanvas({
  nodes = [], macroEdges = [], settledEdges = [], nodeStates = {},
  degreeMap = {}, onNodeClick, pipelineState,
}) {
  const containerRef = useRef(null);
  const sigmaRef = useRef(null);
  const graphRef = useRef(null);
  const [hud, setHud] = useState({ total: 0, zoom: '1.00' });
  const [lightMode, setLightMode] = useState(true);  // 默认白色背景（论文用）
  const [hoverInfo, setHoverInfo] = useState(null);    // 悬停信息

  const colors = lightMode ? LIGHT : DARK;

  // --- 初始化 Sigma ---
  useEffect(() => {
    let cleaned = false;
    const init = async () => {
      if (!containerRef.current || cleaned) return;
      try {
        const { Sigma } = await import('sigma');
        if (cleaned) return;

        const graph = new Graph({ multi: true, type: 'directed' });
        graphRef.current = graph;

        const sigma = new Sigma(graph, containerRef.current, {
          renderEdgeLabels: false,
          enableEdgeEvents: false,
          labelRenderedSizeThreshold: 12,
          defaultNodeColor: colors.default,
          defaultEdgeColor: colors.edgeNormal,
          defaultEdgeType: 'line',
        });
        sigmaRef.current = sigma;

        // 点击节点
        sigma.on('clickNode', ({ node }) => {
          if (onNodeClick) onNodeClick(node);
        });

        // 悬停节点 — 显示度数/边数/余额/风险
        sigma.on('enterNode', ({ node }) => {
          const deg = degreeMap[node] || 0;
          const st = nodeStates[node] || {};
          setHoverInfo({
            id: node,
            degree: deg,
            balance: st.balance || st.final_balance || 0,
            risk: st.risk_level || 'unknown',
            anomalies: st.anomaly_count || 0,
            transactions: st.transaction_count || 0,
          });
        });
        sigma.on('leaveNode', () => setHoverInfo(null));

        sigma.on('afterRender', () => {
          if (cleaned) return;
          const cam = sigma.getCamera();
          setHud({ total: graph.order, zoom: cam ? cam.ratio.toFixed(2) : '1.00' });
        });
      } catch (err) {
        console.error('[SAGA] Sigma init failed:', err);
      }
    };
    init();
    return () => {
      cleaned = true;
      if (sigmaRef.current) { try { sigmaRef.current.kill(); } catch(e){} sigmaRef.current = null; }
      graphRef.current = null;
    };
  }, []);

  // --- 背景色切换 ---
  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.style.backgroundColor = colors.bg;
    }
    // 更新所有节点和边颜色
    const graph = graphRef.current;
    if (!graph) return;
    graph.forEachNode((id) => {
      const st = nodeStates[id];
      graph.setNodeAttribute(id, 'color', st ? riskColor(st.risk_level, colors) : colors.default);
    });
    graph.forEachEdge((id, attrs) => {
      const isAnom = attrs._isAnomaly;
      graph.setEdgeAttribute(id, 'color', isAnom ? colors.edgeAnomaly : colors.edgeNormal);
    });
    if (sigmaRef.current) sigmaRef.current.refresh();
  }, [lightMode, nodeStates]);

  // --- 节点同步 ---
  useEffect(() => {
    const graph = graphRef.current;
    if (!graph || nodes.length === 0) return;
    const maxDeg = Math.max(1, ...Object.values(degreeMap));
    for (const id of nodes) {
      const deg = degreeMap[id] || 1;
      const st = nodeStates[id];
      const color = st ? riskColor(st.risk_level, colors) : colors.default;
      if (!graph.hasNode(id)) {
        graph.addNode(id, { x: Math.random()*100, y: Math.random()*100, size: degreeToSize(deg, maxDeg), color, label: id });
      } else {
        graph.setNodeAttribute(id, 'size', degreeToSize(deg, maxDeg));
        graph.setNodeAttribute(id, 'color', color);
      }
    }
    if (sigmaRef.current) sigmaRef.current.refresh();
  }, [nodes, degreeMap, nodeStates]);

  // --- 边同步 ---
  useEffect(() => {
    const graph = graphRef.current;
    if (!graph) return;
    const edges = settledEdges.length > 0 ? settledEdges : macroEdges;
    if (edges.length === 0) return;
    graph.clearEdges();
    const limit = 50000;
    for (let i = 0; i < Math.min(edges.length, limit); i++) {
      const e = edges[i];
      const src = e.u || e.source || '';
      const tgt = e.v || e.target || '';
      if (!src || !tgt || !graph.hasNode(src) || !graph.hasNode(tgt)) continue;
      const isAnom = e.tag && e.tag !== 'normal';
      try {
        graph.addEdge(src, tgt, {
          color: isAnom ? colors.edgeAnomaly : colors.edgeNormal,
          size: 0.5,
          _isAnomaly: isAnom,  // 存标记供颜色切换用
        });
      } catch (err) {}
    }
    if (sigmaRef.current) sigmaRef.current.refresh();
  }, [settledEdges, macroEdges, lightMode]);

  const isEmpty = nodes.length === 0;

  return (
    <Box sx={{ width: '100%', height: '100%', position: 'relative' }}>
      <Box ref={containerRef} sx={{ width: '100%', height: '100%', bgcolor: lightMode ? '#fff' : 'background.default' }} />

      {isEmpty && (
        <Box sx={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%,-50%)', textAlign: 'center' }}>
          <Typography variant="h6" color="text.disabled">Graph Canvas</Typography>
          <Typography variant="caption" color="text.disabled">Start pipeline to render</Typography>
        </Box>
      )}

      {/* 论文模式切换按钮 */}
      <Tooltip title={lightMode ? 'Switch to dark mode' : 'Paper mode (white background)'}>
        <IconButton
          onClick={() => setLightMode(!lightMode)}
          sx={{ position: 'absolute', top: 8, left: 8, bgcolor: 'rgba(128,128,128,0.3)', '&:hover': { bgcolor: 'rgba(128,128,128,0.5)' } }}
          size="small"
        >
          {lightMode ? <DarkModeIcon fontSize="small" /> : <LightModeIcon fontSize="small" />}
        </IconButton>
      </Tooltip>

      {/* 悬停信息框 */}
      {hoverInfo && (
        <Box sx={{
          position: 'absolute', top: 8, left: 48,
          bgcolor: 'rgba(0,0,0,0.8)', borderRadius: 1, px: 1.5, py: 0.5,
          display: 'flex', gap: 1.5, alignItems: 'center',
        }}>
          <Typography variant="caption" className="mono" sx={{ color: '#fff', fontSize: '0.7rem' }}>
            {hoverInfo.id}
          </Typography>
          <Typography variant="caption" sx={{ color: '#90caf9', fontSize: '0.65rem' }}>
            {hoverInfo.degree} edges
          </Typography>
          <Typography variant="caption" sx={{ color: '#66bb6a', fontSize: '0.65rem' }}>
            ${hoverInfo.balance.toLocaleString()}
          </Typography>
          <Typography variant="caption" sx={{
            color: hoverInfo.risk === 'high' ? '#f44336' : hoverInfo.risk === 'medium' ? '#ffa726' : '#66bb6a',
            fontSize: '0.65rem'
          }}>
            {hoverInfo.risk}
          </Typography>
          {hoverInfo.anomalies > 0 && (
            <Typography variant="caption" sx={{ color: '#f44336', fontSize: '0.65rem' }}>
              {hoverInfo.anomalies} anomaly
            </Typography>
          )}
        </Box>
      )}

      {/* 右下 HUD */}
      {!isEmpty && (
        <Box sx={{ position: 'absolute', bottom: 8, right: 8, bgcolor: 'rgba(0,0,0,0.6)', borderRadius: 1, px: 1, py: 0.5 }}>
          <Typography variant="caption" className="mono" color="text.secondary" sx={{ fontSize: '0.65rem' }}>
            {hud.total} nodes · zoom {hud.zoom}
          </Typography>
        </Box>
      )}

      {settledEdges.length > 50000 && (
        <Chip label="Edges hidden (>50K)" size="small" color="warning" sx={{ position: 'absolute', top: 8, right: 8 }} />
      )}
    </Box>
  );
}
