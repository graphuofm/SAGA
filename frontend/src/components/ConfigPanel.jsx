// ============================================================
// SAGA - 配置面板（清理版：删预设，加 anomaly rate）
// ============================================================
import React, { useState, useCallback, useEffect, useRef } from 'react';
import {
  Box, Typography, TextField, Select, MenuItem, FormControl,
  InputLabel, Switch, FormControlLabel, Slider, Divider,
  FormGroup, Checkbox,
  Accordion, AccordionSummary, AccordionDetails,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import TuneIcon from '@mui/icons-material/Tune';
import AccessTimeIcon from '@mui/icons-material/AccessTime';
import CategoryIcon from '@mui/icons-material/Category';
import OutputIcon from '@mui/icons-material/Output';
import ScenarioSelector from './ScenarioSelector';
import DynamicParams from './DynamicParams';
import RunControls from './RunControls';
import ProgressBar from './ProgressBar';

const OUTPUT_FORMATS = [
  { id: 'csv', label: 'CSV' },
  { id: 'json', label: 'JSON' },
  { id: 'graphml', label: 'GraphML' },
];

export default function ConfigPanel({ state, dispatch, send }) {
  const { pipelineState, connectionState, progress, inferredParams, ragPreview } = state;
  const locked = ['running', 'paused'].includes(pipelineState);

  const [numNodes, setNumNodes] = useState(1000);
  const [numEdges, setNumEdges] = useState(5000);
  const [gamma, setGamma] = useState(2.5);
  const [anomalyRate, setAnomalyRate] = useState(0.1);

  const [timeSpanValue, setTimeSpanValue] = useState(30);
  const [timeSpanUnit, setTimeSpanUnit] = useState('day');
  const [macroBlockUnit, setMacroBlockUnit] = useState('day');
  const [microGranularity, setMicroGranularity] = useState('minute');

  const [useMock, setUseMock] = useState(false);  // 默认 LLM 模式
  const [scenario, setScenario] = useState('');
  const [outputFormats, setOutputFormats] = useState(['csv']);
  const [customRules, setCustomRules] = useState('');

  const [paramValues, setParamValues] = useState({});
  const [activeParams, setActiveParams] = useState([]);
  const [inferLoading, setInferLoading] = useState(false);
  const paramCacheRef = useRef({});

  const [expanded, setExpanded] = useState('graph');
  const handleAccordion = (panel) => (_, isExpanded) => setExpanded(isExpanded ? panel : false);

  // --- 场景选择 + 参数缓存 ---
  const handleScenarioSelect = useCallback((id) => {
    if (scenario && activeParams.length > 0) {
      paramCacheRef.current[scenario] = { params: activeParams, values: { ...paramValues } };
    }
    setScenario(id);
    dispatch({ type: 'SET_SCENARIO', payload: id });

    const cached = paramCacheRef.current[id];
    if (cached) {
      setActiveParams(cached.params);
      setParamValues(cached.values);
      setInferLoading(false);
    } else if (id !== 'custom') {
      send({ type: 'get_rag_preview', scenario: id });
      setInferLoading(true);
      send({ type: 'infer_parameters', scenario: id });
    }
  }, [send, dispatch, scenario, activeParams, paramValues]);

  useEffect(() => {
    if (inferredParams && inferredParams.length > 0) {
      setActiveParams(inferredParams);
      setInferLoading(false);
      const defaults = {};
      for (const p of inferredParams) defaults[p.name] = p.default;
      setParamValues(defaults);
      if (scenario) paramCacheRef.current[scenario] = { params: inferredParams, values: defaults };
    }
  }, [inferredParams]);

  const handleParamChange = (name, value) => setParamValues(prev => ({ ...prev, [name]: value }));
  const handleParamRemove = (name) => {
    setActiveParams(prev => prev.filter(p => p.name !== name));
    setParamValues(prev => { const n = { ...prev }; delete n[name]; return n; });
  };
  const handleParamAdd = (param) => {
    setActiveParams(prev => [...prev, param]);
    setParamValues(prev => ({ ...prev, [param.name]: param.default }));
  };
  const handleReInfer = () => {
    if (scenario) { setInferLoading(true); send({ type: 'infer_parameters', scenario }); }
  };
  const toggleFormat = (id) => setOutputFormats(prev => prev.includes(id) ? prev.filter(f => f !== id) : [...prev, id]);

  // --- Start ---
  const handleStart = () => {
    const config = {
      num_nodes: numNodes, num_edges: numEdges, gamma,
      anomaly_rate: anomalyRate,
      time_span_value: timeSpanValue, time_span_unit: timeSpanUnit,
      macro_block_unit: macroBlockUnit, micro_granularity: microGranularity,
      llm_backend: useMock ? 'mock' : undefined,
      scenario, output_formats: outputFormats,
      user_params: paramValues,
      custom_rules: customRules,
    };
    dispatch({ type: 'START_PIPELINE' });
    dispatch({ type: 'SET_CONFIG', payload: config });
    send({ type: 'start_pipeline', config });
  };

  return (
    <Box>
      <ProgressBar progress={progress} pipelineState={pipelineState} />
      <Divider sx={{ mb: 1 }} />
      <RunControls pipelineState={pipelineState} connectionState={connectionState}
        onStart={handleStart} onPause={() => send({ type: 'pause_pipeline' })}
        onResume={() => send({ type: 'resume_pipeline' })} onStop={() => send({ type: 'stop_pipeline' })} />

      {/* Graph Parameters */}
      <Accordion expanded={expanded === 'graph'} onChange={handleAccordion('graph')} disableGutters
        sx={{ '&:before': { display: 'none' }, bgcolor: 'transparent', boxShadow: 'none' }}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ minHeight: 36, px: 0 }}>
          <TuneIcon sx={{ fontSize: 16, mr: 1, color: 'primary.main' }} />
          <Typography variant="subtitle2">Graph Parameters</Typography>
        </AccordionSummary>
        <AccordionDetails sx={{ px: 0, pt: 0 }}>
          <Box sx={{ display: 'flex', gap: 1, mb: 1 }}>
            <TextField label="Nodes" type="number" value={numNodes}
              onChange={e => setNumNodes(Math.max(1, Number(e.target.value)))} disabled={locked} sx={{ flex: 1 }} />
            <TextField label="Edges" type="number" value={numEdges}
              onChange={e => setNumEdges(Math.max(1, Number(e.target.value)))} disabled={locked} sx={{ flex: 1 }} />
          </Box>
          <Typography variant="caption" color="text.secondary">Power-law γ: {gamma.toFixed(2)}</Typography>
          <Slider value={gamma} onChange={(_, v) => setGamma(v)} min={1.5} max={3.5} step={0.1} disabled={locked} size="small" />
          <Typography variant="caption" color="text.secondary">Anomaly Rate: {(anomalyRate * 100).toFixed(0)}%</Typography>
          <Slider value={anomalyRate} onChange={(_, v) => setAnomalyRate(v)} min={0} max={0.5} step={0.01} disabled={locked} size="small"
            marks={[{value:0.05,label:'5%'},{value:0.1,label:'10%'},{value:0.2,label:'20%'}]} />
        </AccordionDetails>
      </Accordion>

      {/* Time */}
      <Accordion expanded={expanded === 'time'} onChange={handleAccordion('time')} disableGutters
        sx={{ '&:before': { display: 'none' }, bgcolor: 'transparent', boxShadow: 'none' }}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ minHeight: 36, px: 0 }}>
          <AccessTimeIcon sx={{ fontSize: 16, mr: 1, color: 'info.main' }} />
          <Typography variant="subtitle2">Time Dimension</Typography>
        </AccordionSummary>
        <AccordionDetails sx={{ px: 0, pt: 0 }}>
          <Box sx={{ display: 'flex', gap: 1, mb: 1 }}>
            <TextField label="Span" type="number" value={timeSpanValue}
              onChange={e => setTimeSpanValue(Math.max(1, Number(e.target.value)))} disabled={locked} sx={{ flex: 1 }} />
            <FormControl sx={{ minWidth: 80 }}>
              <InputLabel>Unit</InputLabel>
              <Select value={timeSpanUnit} label="Unit" onChange={e => setTimeSpanUnit(e.target.value)} disabled={locked}>
                <MenuItem value="hour">Hour</MenuItem><MenuItem value="day">Day</MenuItem>
                <MenuItem value="week">Week</MenuItem><MenuItem value="month">Month</MenuItem>
              </Select>
            </FormControl>
          </Box>
          <Box sx={{ display: 'flex', gap: 1 }}>
            <FormControl sx={{ flex: 1 }}>
              <InputLabel>Macro</InputLabel>
              <Select value={macroBlockUnit} label="Macro" onChange={e => setMacroBlockUnit(e.target.value)} disabled={locked}>
                <MenuItem value="hour">Hour</MenuItem><MenuItem value="day">Day</MenuItem>
                <MenuItem value="week">Week</MenuItem><MenuItem value="month">Month</MenuItem>
              </Select>
            </FormControl>
            <FormControl sx={{ flex: 1 }}>
              <InputLabel>Micro</InputLabel>
              <Select value={microGranularity} label="Micro" onChange={e => setMicroGranularity(e.target.value)} disabled={locked}>
                <MenuItem value="second">Sec</MenuItem><MenuItem value="minute">Min</MenuItem><MenuItem value="hour">Hour</MenuItem>
              </Select>
            </FormControl>
          </Box>
        </AccordionDetails>
      </Accordion>

      {/* Scenario */}
      <Accordion expanded={expanded === 'scenario'} onChange={handleAccordion('scenario')} disableGutters
        sx={{ '&:before': { display: 'none' }, bgcolor: 'transparent', boxShadow: 'none' }}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ minHeight: 36, px: 0 }}>
          <CategoryIcon sx={{ fontSize: 16, mr: 1, color: 'warning.main' }} />
          <Typography variant="subtitle2">Scenario & Parameters</Typography>
        </AccordionSummary>
        <AccordionDetails sx={{ px: 0, pt: 0 }}>
          <FormControlLabel
            control={<Switch checked={useMock} onChange={e => setUseMock(e.target.checked)} disabled={locked} />}
            label={<Typography variant="body2">{useMock ? 'Mock mode' : 'LLM mode'}</Typography>}
            sx={{ mb: 1 }}
          />
          <ScenarioSelector selected={scenario} onSelect={handleScenarioSelect}
            disabled={locked} ragPreview={ragPreview} onCustomRules={setCustomRules} />
          {scenario && scenario !== 'custom' && (
            <DynamicParams parameters={activeParams} values={paramValues}
              onChange={handleParamChange} onRemove={handleParamRemove}
              onAdd={handleParamAdd} onReInfer={handleReInfer}
              disabled={locked} loading={inferLoading} />
          )}
        </AccordionDetails>
      </Accordion>

      {/* Output */}
      <Accordion expanded={expanded === 'output'} onChange={handleAccordion('output')} disableGutters
        sx={{ '&:before': { display: 'none' }, bgcolor: 'transparent', boxShadow: 'none' }}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ minHeight: 36, px: 0 }}>
          <OutputIcon sx={{ fontSize: 16, mr: 1, color: 'success.main' }} />
          <Typography variant="subtitle2">Output Formats</Typography>
        </AccordionSummary>
        <AccordionDetails sx={{ px: 0, pt: 0 }}>
          <FormGroup row>
            {OUTPUT_FORMATS.map(f => (
              <FormControlLabel key={f.id}
                control={<Checkbox checked={outputFormats.includes(f.id)} onChange={() => toggleFormat(f.id)} disabled={locked} />}
                label={<Typography variant="caption">{f.label}</Typography>} sx={{ mr: 1 }} />
            ))}
          </FormGroup>
        </AccordionDetails>
      </Accordion>
    </Box>
  );
}
