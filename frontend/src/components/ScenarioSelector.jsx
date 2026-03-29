// ============================================================
// SAGA - 场景选择器（Custom 模式支持 RAG 文本输入）
// ============================================================
import React, { useState } from 'react';
import {
  Box, List, ListItemButton, ListItemText, Typography,
  Chip, TextField, Tooltip, IconButton,
} from '@mui/material';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';

const SCENARIOS = [
  { id: 'finance_aml', name: 'Financial AML', desc: 'Anti-money laundering', color: 'success.main' },
  { id: 'network_ids', name: 'Network IDS', desc: 'Intrusion detection', color: 'info.main' },
  { id: 'cyber_apt', name: 'Cyber APT', desc: 'APT attack chain', color: 'error.main' },
  { id: 'traffic', name: 'Traffic', desc: 'Urban transportation', color: 'warning.main' },
  { id: 'custom', name: 'Custom', desc: 'Your own rules', color: 'text.disabled' },
];

const CUSTOM_HELP = `How to use Custom mode:

1. Paste your domain rules in the text box below
2. Describe: what are the nodes? What are the edges?
3. What counts as normal? What counts as anomalous?
4. Include any time patterns (e.g., business hours)
5. Click "Start" — the LLM will generate data following your rules

Example:
"Nodes are IoT devices. Edges are data packets. 
Normal: periodic heartbeat every 60s, <1KB.
Anomaly: burst of >100 packets/min or payload >10KB.
Peak hours: 8AM-6PM."`;

export default function ScenarioSelector({ selected, onSelect, disabled, ragPreview, onCustomRules }) {
  const [customText, setCustomText] = useState('');

  return (
    <Box sx={{ mb: 1.5 }}>
      <Typography variant="subtitle2" sx={{ mb: 0.5 }}>Scenario</Typography>

      <List disablePadding sx={{ mb: 1 }}>
        {SCENARIOS.map((s) => (
          <ListItemButton
            key={s.id}
            selected={selected === s.id}
            disabled={disabled}
            onClick={() => onSelect(s.id)}
            sx={{ borderLeft: 4, borderColor: s.color, borderRadius: 1, mb: 0.5, py: 0.5, px: 1.5 }}
          >
            <ListItemText
              primary={s.name}
              secondary={s.desc}
              primaryTypographyProps={{ variant: 'body2' }}
              secondaryTypographyProps={{ variant: 'caption' }}
            />
          </ListItemButton>
        ))}
      </List>

      {/* Custom 模式：RAG 文本输入 */}
      {selected === 'custom' && (
        <Box sx={{ mb: 1 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 0.5 }}>
            <Typography variant="caption" color="text.secondary">
              Paste your domain rules:
            </Typography>
            <Tooltip title={CUSTOM_HELP} arrow placement="right"
              componentsProps={{ tooltip: { sx: { whiteSpace: 'pre-wrap', maxWidth: 400, fontSize: '0.72rem' } } }}>
              <IconButton size="small"><InfoOutlinedIcon sx={{ fontSize: 14 }} /></IconButton>
            </Tooltip>
          </Box>
          <TextField
            multiline rows={4} fullWidth disabled={disabled}
            placeholder="Describe your nodes, edges, normal behavior, anomaly patterns, and time rules..."
            value={customText}
            onChange={(e) => {
              setCustomText(e.target.value);
              if (onCustomRules) onCustomRules(e.target.value);
            }}
            sx={{ '& textarea': { fontSize: '0.78rem' } }}
          />
        </Box>
      )}

      {/* RAG 预览（非 custom 场景）*/}
      {ragPreview && selected && selected !== 'custom' && (
        <Box sx={{ p: 1, bgcolor: 'action.hover', borderRadius: 1, mb: 1 }}>
          <Box sx={{ display: 'flex', gap: 0.5, mb: 0.5 }}>
            <Chip label={`${ragPreview.rule_count || '?'} rules`} size="small" variant="outlined" />
          </Box>
          <Typography variant="caption" color="text.secondary"
            sx={{ whiteSpace: 'pre-wrap', maxHeight: 60, overflow: 'auto', display: 'block', fontSize: '0.68rem' }}>
            {(ragPreview.rules_text || '').slice(0, 200)}
            {(ragPreview.rules_text || '').length > 200 ? '...' : ''}
          </Typography>
        </Box>
      )}
    </Box>
  );
}
