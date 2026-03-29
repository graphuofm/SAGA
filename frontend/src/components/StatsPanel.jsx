// ============================================================
// SAGA - 统计面板（紧凑版）
// ============================================================
import React from 'react';
import {
  Box, Typography, Divider,
  Accordion, AccordionSummary, AccordionDetails,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { formatNumber, formatAmount } from '../utils/formatters';
import MiniCharts from './MiniCharts';

function Stat({ label, value, color }) {
  return (
    <Box sx={{ display: 'flex', justifyContent: 'space-between', py: 0.3 }}>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography variant="caption" className="mono" sx={{ fontWeight: 600, color: color || 'text.primary' }}>
        {value}
      </Typography>
    </Box>
  );
}

export default function StatsPanel({
  nodes = [], settledEdges = [], anomalies = [], statistics = {},
  nodeStates = {}, degreeMap = {},
}) {
  const totalNodes = nodes.length;
  const totalEdges = statistics.total_edges || settledEdges.length;
  const anomalyEdges = statistics.anomaly_edges ?? anomalies.length;
  const normalEdges = statistics.normal_edges ?? (totalEdges - anomalyEdges);
  const conflictRemoved = statistics.conflict_edges_removed ?? 0;
  const totalAmount = statistics.total_amount_transferred ?? 0;
  const anomalyRate = totalEdges > 0 ? ((anomalyEdges / totalEdges) * 100).toFixed(1) : '0.0';

  const clustering = statistics.clustering_coefficient;
  const numComponents = statistics.num_components;
  const largestRatio = statistics.largest_component_ratio;
  const burstiness = statistics.temporal_burstiness;
  const amountStats = statistics.amount_stats || {};
  const anomalyBreakdown = statistics.anomaly_breakdown || {};
  const intradayDist = statistics.intraday_distribution || [];

  const degreeDist = React.useMemo(() => {
    const counts = {};
    for (const deg of Object.values(degreeMap)) { counts[deg] = (counts[deg] || 0) + 1; }
    return Object.entries(counts).map(([k, v]) => ({ degree: Number(k), count: v })).sort((a, b) => a.degree - b.degree);
  }, [degreeMap]);

  return (
    <Box>
      <Typography variant="subtitle2" sx={{ mb: 0.5 }}>Statistics</Typography>

      <Stat label="Nodes" value={formatNumber(totalNodes)} />
      <Stat label="Edges" value={formatNumber(totalEdges)} />
      <Stat label="Normal" value={formatNumber(normalEdges)} color="success.main" />
      <Stat label={`Anomaly (${anomalyRate}%)`} value={formatNumber(anomalyEdges)} color="error.main" />
      {conflictRemoved > 0 && <Stat label="Conflicts removed" value={formatNumber(conflictRemoved)} color="text.disabled" />}
      <Stat label="Total Transferred" value={formatAmount(totalAmount)} />

      <Divider sx={{ my: 0.5 }} />

      {/* Structure */}
      <Accordion disableGutters sx={{ '&:before': { display: 'none' }, bgcolor: 'transparent', boxShadow: 'none' }}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ minHeight: 28, px: 0 }}>
          <Typography variant="caption" color="text.secondary">Structure</Typography>
        </AccordionSummary>
        <AccordionDetails sx={{ px: 0, pt: 0 }}>
          {clustering != null && <Stat label="Clustering" value={clustering.toFixed(4)} />}
          {numComponents != null && <Stat label="Components" value={`${numComponents} (largest ${((largestRatio||0)*100).toFixed(0)}%)`} />}
          {burstiness != null && <Stat label="Burstiness" value={burstiness.toFixed(3)} />}
          {amountStats.mean != null && (
            <>
              <Stat label="Amt mean/median" value={`$${amountStats.mean?.toLocaleString()} / $${amountStats.median?.toLocaleString()}`} />
              <Stat label="Amt skew/kurt" value={`${amountStats.skew?.toFixed(2)} / ${amountStats.kurtosis?.toFixed(2)}`} />
            </>
          )}
        </AccordionDetails>
      </Accordion>

      <Divider sx={{ my: 0.5 }} />

      <MiniCharts degreeDist={degreeDist} anomalyBreakdown={anomalyBreakdown} intradayDist={intradayDist} />
    </Box>
  );
}
