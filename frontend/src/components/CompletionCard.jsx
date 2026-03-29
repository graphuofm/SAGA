// ============================================================
// SAGA - 完成总结卡片组件
// 第 10 批 / 共 10 批
// 用途：Pipeline 完成后弹出总结对话框
//       显示：总耗时、节点/边数、正常/异常比、质量评分
//       底部直接是导出按钮组
// ============================================================

import React from 'react';
import {
  Dialog, DialogTitle, DialogContent, DialogActions,
  Box, Typography, Button, Divider, Chip, Grid,
} from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import WarningIcon from '@mui/icons-material/Warning';
import DownloadIcon from '@mui/icons-material/Download';
import DescriptionIcon from '@mui/icons-material/Description';
import { formatNumber, formatAmount, formatDuration } from '../utils/formatters';

const HTTP_URL = import.meta.env.VITE_HTTP_URL || 'http://localhost:8080';

/**
 * 单个指标块
 */
function MetricBlock({ label, value, color = 'text.primary' }) {
  return (
    <Box sx={{ textAlign: 'center', p: 1 }}>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography variant="h6" className="mono" sx={{ color, fontSize: '1.2rem' }}>
        {value}
      </Typography>
    </Box>
  );
}

/**
 * 完成总结卡片
 *
 * Props:
 *   open: boolean
 *   onClose: () => void
 *   statistics: { total_edges, normal_edges, anomaly_edges, blocked_edges,
 *                 total_amount_transferred, anomaly_breakdown, ... }
 *   elapsed: number (秒)
 *   totalNodes: number
 *   partial: boolean (是否为用户中止的部分结果)
 *   outputFormats: string[]
 */
export default function CompletionCard({
  open, onClose, statistics = {}, elapsed = 0, totalNodes = 0,
  partial = false, outputFormats = ['json', 'csv'],
}) {
  const totalEdges = statistics.total_edges || 0;
  const normalEdges = statistics.normal_edges || 0;
  const anomalyEdges = statistics.anomaly_edges || 0;
  const blockedEdges = statistics.blocked_edges || 0;
  const totalAmount = statistics.total_amount_transferred || 0;
  const anomalyRate = totalEdges > 0 ? ((anomalyEdges / totalEdges) * 100).toFixed(1) : '0';

  // 质量评分（简易算法：异常率在 5-15% 范围内得高分）
  const qualityScore = (() => {
    if (totalEdges === 0) return 0;
    const rate = anomalyEdges / totalEdges;
    if (rate >= 0.03 && rate <= 0.20) return 95;  // 理想范围
    if (rate >= 0.01 && rate <= 0.30) return 80;
    if (rate > 0) return 60;
    return 40;  // 没有任何异常，数据可能太平淡
  })();

  // 异常分布前 3 名
  const topAnomalies = Object.entries(statistics.anomaly_breakdown || {})
    .sort(([, a], [, b]) => b - a)
    .slice(0, 3);

  const handleDownload = async () => {
    try {
      const url = `${HTTP_URL}/download?formats=${outputFormats.join(',')}`;
      const resp = await fetch(url);
      const blob = await resp.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'saga_output.zip';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    } catch (err) {
      console.error('[SAGA] Download failed:', err);
    }
  };

  const handleDownloadLog = async () => {
    try {
      const resp = await fetch(`${HTTP_URL}/download-log`);
      const blob = await resp.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'saga_run_log.json';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    } catch (err) {
      console.error('[SAGA] Log download failed:', err);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        {partial ? (
          <WarningIcon color="warning" />
        ) : (
          <CheckCircleIcon color="success" />
        )}
        {partial ? 'Pipeline Stopped (Partial)' : 'Pipeline Complete'}
      </DialogTitle>

      <DialogContent>
        {/* 主要指标 2x3 网格 */}
        <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 1, mb: 2 }}>
          <MetricBlock label="Duration" value={formatDuration(elapsed)} />
          <MetricBlock label="Nodes" value={formatNumber(totalNodes)} />
          <MetricBlock label="Edges" value={formatNumber(totalEdges)} />
          <MetricBlock label="Normal" value={formatNumber(normalEdges)} color="success.main" />
          <MetricBlock label="Anomaly" value={`${formatNumber(anomalyEdges)} (${anomalyRate}%)`} color="error.main" />
          <MetricBlock label="Blocked" value={formatNumber(blockedEdges)} />
        </Box>

        <Divider sx={{ mb: 1.5 }} />

        {/* 转账总额 */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
          <Typography variant="body2" color="text.secondary">Total Transferred</Typography>
          <Typography variant="body2" className="mono">{formatAmount(totalAmount)}</Typography>
        </Box>

        {/* 质量评分 */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1.5 }}>
          <Typography variant="body2" color="text.secondary">Quality Score</Typography>
          <Chip
            label={`${qualityScore}/100`}
            color={qualityScore >= 80 ? 'success' : qualityScore >= 60 ? 'warning' : 'error'}
            size="small"
          />
        </Box>

        {/* 异常 Top 3 */}
        {topAnomalies.length > 0 && (
          <>
            <Typography variant="caption" color="text.secondary" sx={{ mb: 0.5, display: 'block' }}>
              Top Anomalies
            </Typography>
            <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mb: 1 }}>
              {topAnomalies.map(([tag, count]) => (
                <Chip
                  key={tag}
                  label={`${tag.replace('anomaly_', '')}: ${count}`}
                  size="small"
                  variant="outlined"
                  color="error"
                />
              ))}
            </Box>
          </>
        )}
      </DialogContent>

      <DialogActions sx={{ px: 3, pb: 2, gap: 1 }}>
        <Button
          variant="contained"
          startIcon={<DownloadIcon />}
          onClick={handleDownload}
        >
          Download Data
        </Button>
        <Button
          variant="outlined"
          startIcon={<DescriptionIcon />}
          onClick={handleDownloadLog}
        >
          Download Log
        </Button>
        <Box sx={{ flex: 1 }} />
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}
