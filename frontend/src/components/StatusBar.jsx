// ============================================================
// SAGA - 顶部状态栏（Phase 联动修复版）
// ============================================================
import React from 'react';
import { AppBar, Toolbar, Box, Typography, Chip } from '@mui/material';
import CircleIcon from '@mui/icons-material/Circle';
import { formatNumber, formatDuration, formatSpeed, phaseName } from '../utils/formatters';

export default function StatusBar({
  connectionState, reconnectCountdown, pipelineState,
  currentPhase, progress, speed,
}) {
  const connColor = connectionState === 'connected' ? 'success'
    : connectionState === 'reconnecting' ? 'warning' : 'error';
  const connText = connectionState === 'connected' ? 'Connected'
    : connectionState === 'reconnecting' ? `Reconnecting (${reconnectCountdown}s)`
    : 'Disconnected';

  // Phase 显示：优先用 progress 里的 current_phase，回退到 prop
  const phase = progress?.current_phase || currentPhase || 0;
  const elapsed = progress?.elapsed_seconds || 0;

  return (
    <AppBar position="static" color="default" elevation={1}
            sx={{ height: 48, minHeight: 48 }}>
      <Toolbar variant="dense" sx={{ minHeight: 48, gap: 1.5 }}>
        {/* SAGA 标题 */}
        <Typography variant="subtitle2" sx={{ fontWeight: 700, mr: 1, whiteSpace: 'nowrap' }}>
          <b>S</b>ynthetic <b>A</b>gentic <b>G</b>raph <b>A</b>rchitecture
        </Typography>

        {/* 连接状态 */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
          <CircleIcon color={connColor} sx={{ fontSize: 10 }} />
          <Typography variant="caption">{connText}</Typography>
        </Box>

        {/* 当前 Phase（实时联动）*/}
        {phase > 0 && (
          <Chip
            label={`Phase ${phase}: ${phaseName(phase)}`}
            color="primary" variant="outlined" size="small"
          />
        )}

        {/* 进度 */}
        <Typography variant="caption" className="mono" sx={{ minWidth: 50 }}>
          {(progress?.overall_progress_percent || 0).toFixed(1)}%
        </Typography>

        <Typography variant="caption" className="mono">
          {formatNumber(progress?.current_edge_index || 0)} / {formatNumber(progress?.total_expected_edges || 0)}
        </Typography>

        <Typography variant="caption" className="mono">
          {formatSpeed(speed)}
        </Typography>

        <Box sx={{ flex: 1 }} />

        <Typography variant="caption" className="mono">
          {formatDuration(elapsed)}
        </Typography>

        <Chip
          label={pipelineState.toUpperCase()}
          color={
            pipelineState === 'running' ? 'primary' :
            pipelineState === 'completed' ? 'success' :
            pipelineState === 'error' ? 'error' :
            pipelineState === 'paused' ? 'warning' : 'default'
          }
          size="small" variant="filled"
        />
      </Toolbar>
    </AppBar>
  );
}
