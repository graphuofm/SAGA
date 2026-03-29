// ============================================================
// SAGA - 回放控制组件
// 用途：Pipeline 完成后回放生成过程
//       拖拽滑块 + 播放/暂停 + 倍速控制
// ============================================================

import React, { useEffect, useRef, useState } from 'react';
import { Box, IconButton, Slider, Typography, ButtonGroup, Button, Tooltip } from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import PauseIcon from '@mui/icons-material/Pause';
import ReplayIcon from '@mui/icons-material/Replay';

const SPEEDS = [1, 2, 5, 10];

/**
 * Props:
 *   totalEdges: number         总边数
 *   replayIndex: number        当前回放到第几条
 *   replaySpeed: number        倍速
 *   replayMode: boolean        是否在回放
 *   onStart: () => void
 *   onStop: () => void
 *   onSetIndex: (idx) => void
 *   onSetSpeed: (speed) => void
 *   pipelineState: string
 */
export default function ReplayControls({
  totalEdges = 0, replayIndex = 0, replaySpeed = 1, replayMode = false,
  onStart, onStop, onSetIndex, onSetSpeed, pipelineState,
}) {
  const [playing, setPlaying] = useState(false);
  const timerRef = useRef(null);

  const canReplay = ['completed', 'stopped'].includes(pipelineState) && totalEdges > 0;

  // 播放定时器
  useEffect(() => {
    if (playing && replayMode) {
      const interval = Math.max(10, 200 / replaySpeed);  // 速度越快间隔越短
      timerRef.current = setInterval(() => {
        onSetIndex(prev => {
          const next = (typeof prev === 'number' ? prev : replayIndex) + 1;
          if (next >= totalEdges) {
            setPlaying(false);
            return totalEdges;
          }
          return next;
        });
      }, interval);
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [playing, replayMode, replaySpeed, totalEdges]);

  const handlePlayPause = () => {
    if (!replayMode) {
      onStart();
      setPlaying(true);
    } else {
      setPlaying(!playing);
    }
  };

  const handleReset = () => {
    setPlaying(false);
    onSetIndex(0);
  };

  if (!canReplay) return null;

  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 1, py: 0.5,
              borderTop: 1, borderColor: 'divider', bgcolor: 'background.paper' }}>
      {/* 播放/暂停 */}
      <IconButton onClick={handlePlayPause} size="small">
        {playing ? <PauseIcon fontSize="small" /> : <PlayArrowIcon fontSize="small" />}
      </IconButton>

      {/* 重置 */}
      <IconButton onClick={handleReset} size="small">
        <ReplayIcon fontSize="small" />
      </IconButton>

      {/* 进度滑块 */}
      <Slider
        value={replayIndex}
        onChange={(_, v) => { setPlaying(false); onSetIndex(v); }}
        min={0}
        max={totalEdges}
        size="small"
        sx={{ flex: 1, mx: 1 }}
      />

      {/* 计数 */}
      <Typography variant="caption" className="mono" sx={{ minWidth: 70, textAlign: 'right' }}>
        {replayIndex}/{totalEdges}
      </Typography>

      {/* 倍速 */}
      <ButtonGroup size="small" variant="outlined" sx={{ ml: 1 }}>
        {SPEEDS.map(s => (
          <Button key={s} onClick={() => onSetSpeed(s)}
            variant={replaySpeed === s ? 'contained' : 'outlined'}
            sx={{ minWidth: 32, px: 0.5 }}>
            {s}x
          </Button>
        ))}
      </ButtonGroup>
    </Box>
  );
}
