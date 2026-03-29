// ============================================================
// SAGA - 运行控制按钮组
// 第 8 批 / 共 10 批
// 用途：开始/暂停/继续/终止按钮，状态机驱动按钮切换
//       终止有确认对话框
// ============================================================

import React, { useState } from 'react';
import {
  Box, Button, Dialog, DialogTitle, DialogContent,
  DialogContentText, DialogActions,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import PauseIcon from '@mui/icons-material/Pause';
import StopIcon from '@mui/icons-material/Stop';

/**
 * 运行控制按钮组
 *
 * Props:
 *   pipelineState: "idle" | "running" | "paused" | "stopped" | "completed" | "error"
 *   connectionState: "connected" | "disconnected" | "reconnecting"
 *   onStart: () => void
 *   onPause: () => void
 *   onResume: () => void
 *   onStop: () => void
 */
export default function RunControls({
  pipelineState, connectionState, onStart, onPause, onResume, onStop,
}) {
  const [stopDialogOpen, setStopDialogOpen] = useState(false);

  const isConnected = connectionState === 'connected';
  const isIdle = pipelineState === 'idle' || pipelineState === 'stopped'
                 || pipelineState === 'completed' || pipelineState === 'error';
  const isRunning = pipelineState === 'running';
  const isPaused = pipelineState === 'paused';

  const handleStop = () => {
    setStopDialogOpen(false);
    onStop();
  };

  return (
    <Box sx={{ display: 'flex', gap: 1, mb: 1.5 }}>
      {/* 开始/继续 按钮 */}
      {isIdle && (
        <Button
          variant="contained"
          color="primary"
          startIcon={<PlayArrowIcon />}
          disabled={!isConnected}
          onClick={onStart}
          fullWidth
        >
          Start
        </Button>
      )}

      {isRunning && (
        <Button
          variant="outlined"
          startIcon={<PauseIcon />}
          onClick={onPause}
          sx={{ flex: 1 }}
        >
          Pause
        </Button>
      )}

      {isPaused && (
        <Button
          variant="contained"
          color="primary"
          startIcon={<PlayArrowIcon />}
          onClick={onResume}
          sx={{ flex: 1 }}
        >
          Resume
        </Button>
      )}

      {/* 终止按钮（运行中或暂停时可用）*/}
      {(isRunning || isPaused) && (
        <Button
          variant="outlined"
          color="error"
          startIcon={<StopIcon />}
          onClick={() => setStopDialogOpen(true)}
          sx={{ flex: 1 }}
        >
          Stop
        </Button>
      )}

      {/* 终止确认对话框 */}
      <Dialog open={stopDialogOpen} onClose={() => setStopDialogOpen(false)}>
        <DialogTitle>Stop Pipeline?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            The pipeline will stop. Data generated so far will be preserved and can be exported.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setStopDialogOpen(false)}>Cancel</Button>
          <Button onClick={handleStop} color="error" variant="contained">
            Stop
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
