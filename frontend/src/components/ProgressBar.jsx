// ============================================================
// SAGA - 双层进度条组件
// 第 8 批 / 共 10 批
// 用途：顶层总进度 + 底层阶段进度 + Phase Stepper
// ============================================================

import React from 'react';
import {
  Box, LinearProgress, Typography, Stepper, Step, StepLabel,
} from '@mui/material';
import { phaseName, formatNumber } from '../utils/formatters';

// 四个阶段定义
const PHASES = [
  { phase: 1, label: 'Skeleton' },
  { phase: 2, label: 'Dispatch' },
  { phase: 3, label: 'Injection' },
  { phase: 4, label: 'Settlement' },
];

/**
 * 双层进度条 + Phase Stepper
 *
 * Props:
 *   progress: { current_phase, current_edge_index, total_expected_edges,
 *               phase_progress_percent, overall_progress_percent,
 *               current_time_block, current_block_index, total_time_blocks }
 *   pipelineState: "idle" | "running" | "paused" | "completed" | ...
 */
export default function ProgressBar({ progress, pipelineState }) {
  const {
    current_phase = 0,
    phase_progress_percent = 0,
    overall_progress_percent = 0,
    current_edge_index = 0,
    total_expected_edges = 0,
    current_time_block = '',
    current_block_index = 0,
    total_time_blocks = 0,
  } = progress || {};

  const isActive = ['running', 'paused'].includes(pipelineState);
  const isDone = pipelineState === 'completed';

  // Stepper 的 activeStep（Phase 1 对应 index 0）
  const activeStep = isDone ? 4 : Math.max(0, current_phase - 1);

  return (
    <Box sx={{ mb: 1.5 }}>
      {/* Phase Stepper（紧凑横向）*/}
      <Stepper activeStep={activeStep} alternativeLabel
               sx={{ mb: 1, '& .MuiStepLabel-label': { fontSize: '0.7rem' } }}>
        {PHASES.map((p) => (
          <Step key={p.phase} completed={current_phase > p.phase || isDone}>
            <StepLabel>{p.label}</StepLabel>
          </Step>
        ))}
      </Stepper>

      {/* 总进度条 */}
      <Box sx={{ mb: 0.5 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.3 }}>
          <Typography variant="caption" color="text.secondary">
            Overall
          </Typography>
          <Typography variant="caption" className="mono">
            {(isDone ? 100 : overall_progress_percent).toFixed(1)}%
          </Typography>
        </Box>
        <LinearProgress
          variant="determinate"
          value={isDone ? 100 : Math.min(100, overall_progress_percent)}
          color={isDone ? 'success' : 'primary'}
          sx={{ height: 6, borderRadius: 1 }}
        />
      </Box>

      {/* 阶段进度条（仅运行中显示）*/}
      {isActive && current_phase > 0 && (
        <Box sx={{ mb: 0.5 }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.3 }}>
            <Typography variant="caption" color="text.secondary">
              Phase {current_phase}: {phaseName(current_phase)}
            </Typography>
            <Typography variant="caption" className="mono">
              {phase_progress_percent.toFixed(1)}%
            </Typography>
          </Box>
          <LinearProgress
            variant="determinate"
            value={Math.min(100, phase_progress_percent)}
            color="info"
            sx={{ height: 4, borderRadius: 1 }}
          />
        </Box>
      )}

      {/* 时间块进度（Phase 3/4 时显示）*/}
      {isActive && current_time_block && (
        <Typography variant="caption" color="text.secondary" className="mono">
          {current_time_block} ({current_block_index}/{total_time_blocks})
          {' · '}
          {formatNumber(current_edge_index)} / {formatNumber(total_expected_edges)} edges
        </Typography>
      )}
    </Box>
  );
}
