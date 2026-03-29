// ============================================================
// SAGA - React 入口文件
// 第 7 批 / 共 10 批
// 用途：挂载 React 根组件，配置 MUI M3 Dark Theme
// ============================================================

import React from 'react';
import ReactDOM from 'react-dom/client';
import { ThemeProvider, CssBaseline, createTheme } from '@mui/material';
import App from './App';
import './index.css';

// M3 Light Theme 配置（白色背景，适合论文截图）
const theme = createTheme({
  palette: {
    mode: 'light',
  },
  typography: {
    fontFamily: '"Roboto", "Helvetica", "Arial", sans-serif',
  },
  components: {
    MuiTextField: { defaultProps: { size: 'small' } },
    MuiButton: { defaultProps: { size: 'small' } },
    MuiSelect: { defaultProps: { size: 'small' } },
    MuiSwitch: { defaultProps: { size: 'small' } },
    MuiCheckbox: { defaultProps: { size: 'small' } },
    MuiIconButton: { defaultProps: { size: 'small' } },
    MuiChip: { defaultProps: { size: 'small' } },
    MuiList: { defaultProps: { dense: true } },
    MuiTable: { defaultProps: { size: 'small' } },
  },
});

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ThemeProvider theme={theme}>
      {/* CssBaseline 注入 M3 Dark 全局样式（深色背景等） */}
      <CssBaseline />
      <App />
    </ThemeProvider>
  </React.StrictMode>
);
