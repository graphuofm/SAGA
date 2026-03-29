// ============================================================
// SAGA - 节点详情抽屉组件
// 第 9 批 / 共 10 批
// 用途：点击图上节点后弹出右侧 Drawer 显示详情
//       包含：节点状态表、关联边列表、时间线
// ============================================================

import React from 'react';
import {
  Drawer, Box, Typography, IconButton, Divider, Chip,
  Table, TableBody, TableRow, TableCell, List, ListItem, ListItemText,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import { formatNumber, formatAmount, riskToColor, tagToColor } from '../utils/formatters';

/**
 * 节点详情抽屉
 *
 * Props:
 *   open: boolean
 *   onClose: () => void
 *   nodeDetail: { node_id, current_state, related_edges, timeline } 或 null
 *   nodeStates: object（实时状态，作为 nodeDetail 的回退）
 */
export default function NodeDetail({ open, onClose, nodeDetail, nodeStates = {}, selectedNodeId, settledEdges = [] }) {
  if (!open) return null;

  const nodeId = selectedNodeId || nodeDetail?.node_id || '';
  // 优先用 nodeDetail 中的状态，回退到 nodeStates
  const state = nodeDetail?.current_state || nodeStates[nodeId] || {};
  const relatedEdges = nodeDetail?.related_edges || [];

  // 修复 #16: 从 settledEdges 自动构建 timeline（不依赖服务器返回）
  const timeline = React.useMemo(() => {
    if (nodeDetail?.timeline?.length > 0) return nodeDetail.timeline;
    if (!nodeId || settledEdges.length === 0) return [];
    // 从已结算边中过滤出该节点参与的所有交易
    return settledEdges
      .filter(e => e.u === nodeId || e.v === nodeId)
      .map(e => ({
        time: e.time || '',
        tag: e.tag || 'normal',
        role: e.u === nodeId ? 'sender' : 'receiver',
        counterparty: e.u === nodeId ? e.v : e.u,
        amount: e.amt || 0,
        status: e.status || 'success',
      }))
      .slice(-50);  // 最多50条
  }, [nodeId, settledEdges, nodeDetail]);

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      PaperProps={{ sx: { width: 340, p: 2, bgcolor: 'background.paper' } }}
    >
      {/* 标题栏 */}
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
        <Typography variant="subtitle1" className="mono">{nodeId}</Typography>
        <IconButton onClick={onClose} size="small"><CloseIcon /></IconButton>
      </Box>

      {/* 风险标签 */}
      <Box sx={{ mb: 1.5, display: 'flex', gap: 0.5 }}>
        <Chip
          label={state.risk_level || 'unknown'}
          color={riskToColor(state.risk_level)}
          size="small"
        />
        <Chip
          label={state.status || 'unknown'}
          variant="outlined"
          size="small"
          color={state.status === 'frozen' ? 'default' : 'primary'}
        />
      </Box>

      {/* 状态表 */}
      <Typography variant="subtitle2" sx={{ mb: 0.5 }}>State</Typography>
      <Table size="small" sx={{ mb: 2, '& td': { py: 0.5, fontSize: '0.78rem' } }}>
        <TableBody>
          <TableRow>
            <TableCell sx={{ color: 'text.secondary' }}>Balance</TableCell>
            <TableCell align="right" className="mono">{formatAmount(state.balance)}</TableCell>
          </TableRow>
          <TableRow>
            <TableCell sx={{ color: 'text.secondary' }}>Degree (edges)</TableCell>
            <TableCell align="right" className="mono">{formatNumber(state.transaction_count || relatedEdges.length)}</TableCell>
          </TableRow>
          <TableRow>
            <TableCell sx={{ color: 'text.secondary' }}>Anomaly Edges</TableCell>
            <TableCell align="right" className="mono" sx={{ color: (state.anomaly_count || 0) > 0 ? 'error.main' : 'text.primary' }}>
              {formatNumber(state.anomaly_count)} / {formatNumber(state.transaction_count || relatedEdges.length)}
            </TableCell>
          </TableRow>
          <TableRow>
            <TableCell sx={{ color: 'text.secondary' }}>Counterparties</TableCell>
            <TableCell align="right" className="mono">
              {Array.isArray(state.counterparties) ? state.counterparties.length : '—'}
            </TableCell>
          </TableRow>
          <TableRow>
            <TableCell sx={{ color: 'text.secondary' }}>Last Tx</TableCell>
            <TableCell align="right" className="mono" sx={{ fontSize: '0.7rem' }}>
              {state.last_transaction_time || '—'}
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>

      <Divider sx={{ mb: 1.5 }} />

      {/* 时间线（最近 20 条）*/}
      <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
        Timeline ({timeline.length} events)
      </Typography>

      <List disablePadding sx={{ maxHeight: 300, overflow: 'auto' }}>
        {timeline.slice(-20).map((evt, idx) => (
          <ListItem key={idx} disablePadding sx={{ mb: 0.5 }}>
            <ListItemText
              primary={
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  <Typography variant="caption" className="mono" color="text.disabled" sx={{ fontSize: '0.65rem', minWidth: 80 }}>
                    {evt.time}
                  </Typography>
                  <Chip
                    label={evt.tag || 'normal'}
                    size="small"
                    color={tagToColor(evt.tag)}
                    sx={{ height: 18, fontSize: '0.6rem' }}
                  />
                </Box>
              }
              secondary={
                <Typography variant="caption" sx={{ fontSize: '0.7rem' }}>
                  {evt.role === 'sender' ? '→' : '←'} {evt.counterparty} {formatAmount(evt.amount)}
                  {evt.status === 'blocked' && ' [BLOCKED]'}
                  {evt.status === 'failed' && ' [FAILED]'}
                </Typography>
              }
            />
          </ListItem>
        ))}
        {timeline.length === 0 && (
          <Typography variant="caption" color="text.disabled" sx={{ p: 1 }}>
            No events yet
          </Typography>
        )}
      </List>

      {timeline.length > 20 && (
        <Typography variant="caption" color="text.disabled" sx={{ mt: 0.5, display: 'block' }}>
          Showing last 20 of {timeline.length}
        </Typography>
      )}

      <Divider sx={{ my: 1.5 }} />

      {/* 关联边数 */}
      <Typography variant="caption" color="text.secondary">
        {relatedEdges.length} related edges
      </Typography>
    </Drawer>
  );
}
