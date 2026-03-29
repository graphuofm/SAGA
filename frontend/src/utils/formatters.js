// ============================================================
// SAGA - 数据格式化工具函数
// 第 7 批 / 共 10 批
// 用途：前端各组件共用的数据格式化、转换函数
// ============================================================

/**
 * 格式化数字为带千分位的字符串
 * 12450 → "12,450"
 */
export function formatNumber(num) {
  if (num == null || isNaN(num)) return '0';
  return Number(num).toLocaleString('en-US');
}

/**
 * 格式化字节数为可读大小
 * 1536000 → "1.46 MB"
 */
export function formatBytes(bytes) {
  if (bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  const val = bytes / Math.pow(1024, i);
  return val.toFixed(i > 0 ? 2 : 0) + ' ' + units[i];
}

/**
 * 格式化秒数为可读时间
 * 3661 → "1h 1m 1s"
 * 45 → "45s"
 */
export function formatDuration(seconds) {
  if (seconds == null || seconds < 0) return '—';
  if (seconds < 1) return '<1s';

  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);

  const parts = [];
  if (h > 0) parts.push(h + 'h');
  if (m > 0) parts.push(m + 'm');
  if (s > 0 || parts.length === 0) parts.push(s + 's');
  return parts.join(' ');
}

/**
 * 格式化速度（边/秒）
 * 1234.5 → "1,235 edges/s"
 */
export function formatSpeed(edgesPerSec) {
  if (edgesPerSec == null || edgesPerSec <= 0) return '— edges/s';
  return formatNumber(Math.round(edgesPerSec)) + ' edges/s';
}

/**
 * 格式化百分比
 * 0.7845 → "78.5%"
 */
export function formatPercent(ratio, decimals = 1) {
  if (ratio == null || isNaN(ratio)) return '0%';
  return (ratio * 100).toFixed(decimals) + '%';
}

/**
 * 格式化金额（美元）
 * 15000 → "$15,000"
 */
export function formatAmount(amount) {
  if (amount == null) return '$0';
  return '$' + formatNumber(amount);
}

/**
 * 缩短节点 ID 用于显示
 * "N_00001234" → "N_1234" （如果宽度不够时用）
 */
export function shortenNodeId(id, maxLen = 8) {
  if (!id) return '';
  if (id.length <= maxLen) return id;
  return id.slice(0, 2) + '…' + id.slice(-4);
}

/**
 * 风险等级 → M3 语义色名称映射
 * 供 MUI color prop 使用：<Chip color={riskToColor('high')} />
 */
export function riskToColor(riskLevel) {
  const map = {
    low: 'success',
    medium: 'warning',
    high: 'error',
    frozen: 'default',
  };
  return map[riskLevel] || 'default';
}

/**
 * 异常标签 → M3 语义色名称映射
 */
export function tagToColor(tag) {
  if (!tag || tag === 'normal') return 'success';
  if (tag.includes('blocked')) return 'default';
  return 'error';
}

/**
 * Pipeline 状态 → M3 语义色映射
 */
export function stateToColor(state) {
  const map = {
    idle: 'default',
    running: 'primary',
    paused: 'warning',
    stopped: 'default',
    completed: 'success',
    error: 'error',
  };
  return map[state] || 'default';
}

/**
 * Phase 编号 → 名称
 */
export function phaseName(phase) {
  const names = {
    1: 'Skeleton',
    2: 'Dispatch',
    3: 'Injection',
    4: 'Settlement',
  };
  return names[phase] || 'Phase ' + phase;
}

/**
 * 计算速度（边/秒）：维护滑动窗口
 * 调用方式：在 useReducer 中每收到边更新时调用
 */
export function calcSpeed(prevEdgeCount, currentEdgeCount, elapsedSeconds) {
  if (elapsedSeconds <= 0) return 0;
  return (currentEdgeCount - prevEdgeCount) / elapsedSeconds;
}
