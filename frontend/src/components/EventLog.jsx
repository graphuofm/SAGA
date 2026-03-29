// ============================================================
// SAGA - 事件日志组件
// 第 9 批 / 共 10 批
// 用途：底部终端风格实时滚动日志
//       颜色分级：phase=紫 success=绿 error=红 warning=橙 info=灰
//       自动滚动到底部，支持筛选
// ============================================================

import React, { useRef, useEffect, useState } from 'react';
import { Box, Typography, TextField, IconButton, InputAdornment } from '@mui/material';
import FilterListIcon from '@mui/icons-material/FilterList';
import DeleteSweepIcon from '@mui/icons-material/DeleteSweep';

// 日志级别 → M3 语义色
const LEVEL_COLORS = {
  phase: 'primary.main',
  success: 'success.main',
  error: 'error.main',
  warning: 'warning.main',
  info: 'text.secondary',
};

/**
 * 事件日志组件
 *
 * Props:
 *   eventLog: [{ time, level, message }, ...]
 *   onClear: () => void   清空日志
 */
export default function EventLog({ eventLog = [], onClear }) {
  const scrollRef = useRef(null);
  const [filter, setFilter] = useState('');
  const [autoScroll, setAutoScroll] = useState(true);

  // 自动滚动到底部
  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [eventLog.length, autoScroll]);

  // 检测用户是否手动滚动（如果滚到上方就暂停自动滚动）
  const handleScroll = () => {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    // 距离底部 30px 以内认为在底部
    setAutoScroll(scrollHeight - scrollTop - clientHeight < 30);
  };

  // 过滤
  const filtered = filter
    ? eventLog.filter(e => e.message.toLowerCase().includes(filter.toLowerCase()))
    : eventLog;

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* 工具栏 */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 0.5, flexShrink: 0 }}>
        <TextField
          placeholder="Filter logs..."
          value={filter}
          onChange={e => setFilter(e.target.value)}
          size="small"
          sx={{ flex: 1, '& input': { fontSize: '0.75rem', py: 0.5 } }}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <FilterListIcon sx={{ fontSize: 14, color: 'text.disabled' }} />
              </InputAdornment>
            ),
          }}
        />
        {onClear && (
          <IconButton onClick={onClear} size="small">
            <DeleteSweepIcon fontSize="small" />
          </IconButton>
        )}
        <Typography variant="caption" color="text.disabled" sx={{ minWidth: 40, textAlign: 'right' }}>
          {filtered.length}
        </Typography>
      </Box>

      {/* 日志列表 */}
      <Box
        ref={scrollRef}
        onScroll={handleScroll}
        sx={{
          flex: 1,
          overflow: 'auto',
          fontFamily: '"Roboto Mono", monospace',
        }}
      >
        {filtered.map((entry, idx) => (
          <Typography
            key={idx}
            variant="caption"
            component="div"
            sx={{
              color: LEVEL_COLORS[entry.level] || 'text.secondary',
              fontFamily: '"Roboto Mono", monospace',
              lineHeight: 1.6,
              fontSize: '0.7rem',
              px: 0.5,
              '&:hover': { bgcolor: 'rgba(255,255,255,0.03)' },
            }}
          >
            <Typography component="span" variant="caption"
              sx={{ color: 'text.disabled', fontFamily: 'inherit', fontSize: 'inherit', mr: 0.5 }}>
              [{entry.time}]
            </Typography>
            {entry.message}
          </Typography>
        ))}

        {filtered.length === 0 && (
          <Typography variant="caption" color="text.disabled" sx={{ p: 1 }}>
            {filter ? 'No matching logs' : 'Waiting for events...'}
          </Typography>
        )}
      </Box>

      {/* 自动滚动指示 */}
      {!autoScroll && eventLog.length > 0 && (
        <Box
          onClick={() => {
            setAutoScroll(true);
            if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
          }}
          sx={{
            textAlign: 'center', py: 0.3, cursor: 'pointer',
            bgcolor: 'primary.main', color: 'primary.contrastText',
            fontSize: '0.65rem', borderRadius: 1,
          }}
        >
          New logs ↓ Click to scroll
        </Box>
      )}
    </Box>
  );
}
