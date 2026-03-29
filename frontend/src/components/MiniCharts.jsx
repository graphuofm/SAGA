// ============================================================
// SAGA - 迷你图表（degree distribution 修复）
// ============================================================
import React from 'react';
import { Box, Typography, Accordion, AccordionSummary, AccordionDetails } from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import {
  ScatterChart, Scatter, XAxis, YAxis, Tooltip as ReTooltip,
  ResponsiveContainer, PieChart, Pie, Cell,
  BarChart, Bar,
} from 'recharts';

const PIE_COLORS = ['#f44336', '#ff9800', '#ffa726', '#66bb6a', '#42a5f5', '#ab47bc', '#78909c'];

export default function MiniCharts({ degreeDist = [], anomalyBreakdown = {}, intradayDist = [] }) {
  const pieData = Object.entries(anomalyBreakdown)
    .filter(([, v]) => v > 0)
    .map(([name, value]) => ({ name: name.replace('anomaly_', ''), value }))
    .sort((a, b) => b.value - a.value);

  const hourData = intradayDist.length > 0
    ? intradayDist.map(([h, c]) => ({ hour: h, count: c }))
    : [];

  // 度分布：过滤掉 degree=0 和 count=0，用线性轴兜底
  const validDegree = degreeDist.filter(d => d.degree > 0 && d.count > 0);
  const useLogScale = validDegree.length > 3 && validDegree[validDegree.length - 1].degree > 10;

  return (
    <Box>
      {/* 度分布 — 一定渲染 */}
      {validDegree.length > 0 && (
        <Accordion defaultExpanded disableGutters sx={{ '&:before': { display: 'none' }, bgcolor: 'transparent', boxShadow: 'none' }}>
          <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ minHeight: 28, px: 0 }}>
            <Typography variant="caption" color="text.secondary">Degree Distribution ({validDegree.length} points)</Typography>
          </AccordionSummary>
          <AccordionDetails sx={{ px: 0, pt: 0 }}>
            <ResponsiveContainer width="100%" height={120}>
              <ScatterChart margin={{ top: 5, right: 5, bottom: 5, left: 0 }}>
                <XAxis dataKey="degree" type="number"
                  scale={useLogScale ? "log" : "linear"}
                  domain={useLogScale ? ['auto', 'auto'] : [0, 'auto']}
                  tick={{ fontSize: 9, fill: '#666' }} tickLine={false}
                  allowDecimals={false} />
                <YAxis dataKey="count" type="number"
                  scale={useLogScale ? "log" : "linear"}
                  domain={useLogScale ? ['auto', 'auto'] : [0, 'auto']}
                  tick={{ fontSize: 9, fill: '#666' }} tickLine={false} width={28}
                  allowDecimals={false} />
                <ReTooltip contentStyle={{ backgroundColor: '#fff', border: '1px solid #ccc', fontSize: 11 }}
                  formatter={(val, name) => [val, name === 'degree' ? 'Degree' : 'Count']} />
                <Scatter data={validDegree} fill="#1976d2" fillOpacity={0.7} r={3} />
              </ScatterChart>
            </ResponsiveContainer>
          </AccordionDetails>
        </Accordion>
      )}

      {/* 异常饼图 */}
      {pieData.length > 0 && (
        <Accordion disableGutters sx={{ '&:before': { display: 'none' }, bgcolor: 'transparent', boxShadow: 'none' }}>
          <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ minHeight: 28, px: 0 }}>
            <Typography variant="caption" color="text.secondary">Anomaly Types</Typography>
          </AccordionSummary>
          <AccordionDetails sx={{ px: 0, pt: 0 }}>
            <ResponsiveContainer width="100%" height={140}>
              <PieChart>
                <Pie data={pieData} cx="50%" cy="50%" innerRadius={22} outerRadius={45}
                  dataKey="value" paddingAngle={2}
                  label={({ name, percent }) => percent > 0.05 ? `${name} ${(percent*100).toFixed(0)}%` : ''}
                  labelLine={false} style={{ fontSize: 8 }}>
                  {pieData.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
                </Pie>
                <ReTooltip contentStyle={{ backgroundColor: '#fff', border: '1px solid #ccc', fontSize: 11 }} />
              </PieChart>
            </ResponsiveContainer>
          </AccordionDetails>
        </Accordion>
      )}

      {/* 日内分布 */}
      {hourData.length > 0 && (
        <Accordion disableGutters sx={{ '&:before': { display: 'none' }, bgcolor: 'transparent', boxShadow: 'none' }}>
          <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ minHeight: 28, px: 0 }}>
            <Typography variant="caption" color="text.secondary">Intraday Distribution</Typography>
          </AccordionSummary>
          <AccordionDetails sx={{ px: 0, pt: 0 }}>
            <ResponsiveContainer width="100%" height={100}>
              <BarChart data={hourData} margin={{ top: 5, right: 5, bottom: 5, left: 0 }}>
                <XAxis dataKey="hour" tick={{ fontSize: 8, fill: '#666' }} tickLine={false} interval={5} />
                <YAxis tick={{ fontSize: 8, fill: '#666' }} tickLine={false} width={25} />
                <ReTooltip contentStyle={{ backgroundColor: '#fff', border: '1px solid #ccc', fontSize: 11 }}
                  formatter={(v) => [v, 'edges']} labelFormatter={(h) => `${h}:00`} />
                <Bar dataKey="count" fill="#1976d2" fillOpacity={0.6} radius={[2,2,0,0]} />
              </BarChart>
            </ResponsiveContainer>
          </AccordionDetails>
        </Accordion>
      )}
    </Box>
  );
}
