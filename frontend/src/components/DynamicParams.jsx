// ============================================================
// SAGA - 动态参数列表组件
// 第 8 批 / 共 10 批
// 用途：根据 LLM 推断的参数数组动态渲染控件
//       支持 number / slider / select / text 类型
//       支持 ➕ 添加自定义参数、➖ 删除参数
// ============================================================

import React, { useState } from 'react';
import {
  Box, Typography, List, ListItem, IconButton, TextField,
  Slider, Select, MenuItem, Switch, Tooltip, Divider,
  FormControl, InputLabel, Dialog, DialogTitle, DialogContent,
  DialogActions, Button,
} from '@mui/material';
import RemoveCircleOutlineIcon from '@mui/icons-material/RemoveCircleOutline';
import AddCircleOutlineIcon from '@mui/icons-material/AddCircleOutline';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import RefreshIcon from '@mui/icons-material/Refresh';

/**
 * 动态参数列表
 *
 * Props:
 *   parameters: [{ name, label, type, default, min, max, step, options, description }, ...]
 *   values: { paramName: currentValue, ... }  当前参数值
 *   onChange: (paramName, newValue) => void
 *   onRemove: (paramName) => void
 *   onAdd: (param) => void   添加自定义参数
 *   onReInfer: () => void    重新推断
 *   disabled: boolean        运行中锁定
 *   loading: boolean         正在推断中
 */
export default function DynamicParams({
  parameters = [], values = {}, onChange, onRemove, onAdd, onReInfer,
  disabled = false, loading = false,
}) {
  const [addDialogOpen, setAddDialogOpen] = useState(false);
  const [newParam, setNewParam] = useState({ name: '', type: 'number', default: 0, description: '' });

  // 获取参数当前值（优先用 values 中的值，否则用 default）
  const getValue = (param) => {
    if (param.name in values) return values[param.name];
    return param.default;
  };

  // 添加自定义参数
  const handleAddConfirm = () => {
    if (newParam.name.trim()) {
      onAdd({
        ...newParam,
        name: newParam.name.trim().replace(/\s+/g, '_').toLowerCase(),
        label: newParam.name.trim(),
        custom: true,
      });
    }
    setNewParam({ name: '', type: 'number', default: 0, description: '' });
    setAddDialogOpen(false);
  };

  if (parameters.length === 0 && !loading) {
    return (
      <Box sx={{ mb: 1.5 }}>
        <Typography variant="caption" color="text.secondary">
          Select a scenario to infer parameters
        </Typography>
      </Box>
    );
  }

  return (
    <Box sx={{ mb: 1.5 }}>
      {/* 标题栏 */}
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 0.5 }}>
        <Typography variant="subtitle2">
          Parameters
          {parameters.length > 0 && (
            <Typography variant="caption" color="text.secondary" component="span">
              {' '}({parameters.length})
            </Typography>
          )}
        </Typography>
        {onReInfer && (
          <Tooltip title="Re-infer parameters">
            <span>
              <IconButton onClick={onReInfer} disabled={disabled || loading} size="small">
                <RefreshIcon fontSize="small" />
              </IconButton>
            </span>
          </Tooltip>
        )}
      </Box>

      {loading && (
        <Typography variant="caption" color="info.main" sx={{ mb: 1, display: 'block' }}>
          Inferring parameters...
        </Typography>
      )}

      {/* 参数列表 */}
      <List disablePadding>
        {parameters.map((param) => (
          <ListItem
            key={param.name}
            disablePadding
            sx={{ mb: 1, display: 'block' }}
          >
            {/* 参数头部：删除按钮 + 名称 + info */}
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 0.3 }}>
              <IconButton
                onClick={() => onRemove(param.name)}
                disabled={disabled}
                sx={{ p: 0.3 }}
              >
                <RemoveCircleOutlineIcon fontSize="small" color="error" />
              </IconButton>
              <Typography variant="body2" sx={{ flex: 1, fontSize: '0.8rem' }}>
                {param.label || param.name}
                {param.custom && (
                  <Typography variant="caption" color="info.main" component="span"> (custom)</Typography>
                )}
              </Typography>
              {param.description && (
                <Tooltip title={param.description} arrow>
                  <InfoOutlinedIcon sx={{ fontSize: 14, color: 'text.disabled' }} />
                </Tooltip>
              )}
            </Box>

            {/* 参数控件（根据 type 动态渲染）*/}
            <Box sx={{ pl: 3.5 }}>
              <ParamControl
                param={param}
                value={getValue(param)}
                onChange={(val) => onChange(param.name, val)}
                disabled={disabled}
              />
            </Box>
          </ListItem>
        ))}
      </List>

      {/* ➕ 添加自定义参数 */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mt: 0.5 }}>
        <IconButton onClick={() => setAddDialogOpen(true)} disabled={disabled} size="small">
          <AddCircleOutlineIcon fontSize="small" color="primary" />
        </IconButton>
        <Typography variant="caption" color="text.secondary">
          Add custom parameter
        </Typography>
      </Box>

      {/* 添加对话框 */}
      <Dialog open={addDialogOpen} onClose={() => setAddDialogOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Add Custom Parameter</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
          <TextField
            label="Parameter Name"
            value={newParam.name}
            onChange={(e) => setNewParam({ ...newParam, name: e.target.value })}
            size="small"
            autoFocus
          />
          <FormControl size="small">
            <InputLabel>Type</InputLabel>
            <Select
              label="Type"
              value={newParam.type}
              onChange={(e) => setNewParam({ ...newParam, type: e.target.value })}
            >
              <MenuItem value="number">Number</MenuItem>
              <MenuItem value="slider">Slider</MenuItem>
              <MenuItem value="select">Select</MenuItem>
              <MenuItem value="text">Text</MenuItem>
            </Select>
          </FormControl>
          <TextField
            label="Default Value"
            value={newParam.default}
            onChange={(e) => setNewParam({ ...newParam, default: e.target.value })}
            size="small"
          />
          <TextField
            label="Description"
            value={newParam.description}
            onChange={(e) => setNewParam({ ...newParam, description: e.target.value })}
            size="small"
            multiline
            rows={2}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAddDialogOpen(false)}>Cancel</Button>
          <Button onClick={handleAddConfirm} variant="contained" disabled={!newParam.name.trim()}>
            Add
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}


/**
 * 单个参数控件（根据 type 渲染）
 */
function ParamControl({ param, value, onChange, disabled }) {
  const { type } = param;

  if (type === 'slider') {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <Slider
          value={typeof value === 'number' ? value : param.default || 0}
          onChange={(_, v) => onChange(v)}
          min={param.min ?? 0}
          max={param.max ?? 100}
          step={param.step ?? 1}
          disabled={disabled}
          size="small"
          sx={{ flex: 1 }}
        />
        <Typography variant="caption" className="mono" sx={{ minWidth: 36, textAlign: 'right' }}>
          {typeof value === 'number' ? value : param.default}
        </Typography>
      </Box>
    );
  }

  if (type === 'select') {
    return (
      <Select
        value={value ?? param.default ?? ''}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        size="small"
        fullWidth
      >
        {(param.options || []).map((opt) => (
          <MenuItem key={opt} value={opt}>{opt}</MenuItem>
        ))}
      </Select>
    );
  }

  if (type === 'text') {
    return (
      <TextField
        value={value ?? param.default ?? ''}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        size="small"
        fullWidth
        multiline={String(value || '').length > 50}
      />
    );
  }

  // 默认：number
  return (
    <TextField
      type="number"
      value={value ?? param.default ?? 0}
      onChange={(e) => onChange(Number(e.target.value))}
      disabled={disabled}
      size="small"
      fullWidth
      inputProps={{
        min: param.min,
        max: param.max,
        step: param.step || 1,
      }}
    />
  );
}
