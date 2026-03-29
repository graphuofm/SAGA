// ============================================================
// SAGA - 导出工具栏组件
// 第 10 批 / 共 10 批
// 用途：下载数据 ZIP / 下载 Log / 截图 按钮组
//       调用后端 HTTP 接口下载
// ============================================================

import React, { useState } from 'react';
import {
  Box, Typography, Button, ButtonGroup, Tooltip,
  CircularProgress,
} from '@mui/material';
import DownloadIcon from '@mui/icons-material/Download';
import DescriptionIcon from '@mui/icons-material/Description';
import PhotoCameraIcon from '@mui/icons-material/PhotoCamera';

// 从环境变量读取 HTTP 地址
const HTTP_URL = import.meta.env.VITE_HTTP_URL || 'http://localhost:8080';

/**
 * 导出工具栏
 *
 * Props:
 *   pipelineState: string
 *   outputFormats: string[]  用户选择的输出格式
 *   hasData: boolean         是否有可导出的数据
 */
export default function ExportToolbar({ pipelineState, outputFormats = ['json', 'csv'], hasData = false }) {
  const [downloading, setDownloading] = useState(null); // 'data' | 'log' | null

  const canExport = hasData && ['completed', 'stopped'].includes(pipelineState);

  // --- 下载数据 ZIP ---
  const handleDownloadData = async () => {
    setDownloading('data');
    try {
      const formats = outputFormats.join(',');
      const url = `${HTTP_URL}/download?formats=${formats}`;
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const blob = await resp.blob();
      // 触发浏览器下载
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'saga_output.zip';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(a.href);
    } catch (err) {
      console.error('[SAGA] Download failed:', err);
    } finally {
      setDownloading(null);
    }
  };

  // --- 下载运行日志 ---
  const handleDownloadLog = async () => {
    setDownloading('log');
    try {
      const url = `${HTTP_URL}/download-log`;
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const blob = await resp.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'saga_run_log.json';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(a.href);
    } catch (err) {
      console.error('[SAGA] Log download failed:', err);
    } finally {
      setDownloading(null);
    }
  };

  // --- 截图 ---
  const handleScreenshot = () => {
    // 获取 Sigma 画布或整个中央区域截图
    const canvas = document.querySelector('canvas');
    if (!canvas) {
      console.warn('[SAGA] No canvas found for screenshot');
      return;
    }
    try {
      const dataUrl = canvas.toDataURL('image/png');
      const a = document.createElement('a');
      a.href = dataUrl;
      a.download = `saga_graph_${Date.now()}.png`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    } catch (err) {
      console.error('[SAGA] Screenshot failed:', err);
    }
  };

  return (
    <Box>
      <Typography variant="subtitle2" sx={{ mb: 1 }}>Export</Typography>

      {/* 下载数据 */}
      <Tooltip title={canExport ? `Download ${outputFormats.join(', ')} as ZIP` : 'Run pipeline first'}>
        <span>
          <Button
            variant="outlined"
            startIcon={downloading === 'data' ? <CircularProgress size={14} /> : <DownloadIcon />}
            onClick={handleDownloadData}
            disabled={!canExport || downloading === 'data'}
            fullWidth
            sx={{ mb: 1, justifyContent: 'flex-start' }}
          >
            Download Data
          </Button>
        </span>
      </Tooltip>

      {/* 下载日志 */}
      <Tooltip title={canExport ? 'Download full run log (JSON)' : 'Run pipeline first'}>
        <span>
          <Button
            variant="outlined"
            startIcon={downloading === 'log' ? <CircularProgress size={14} /> : <DescriptionIcon />}
            onClick={handleDownloadLog}
            disabled={!canExport || downloading === 'log'}
            fullWidth
            sx={{ mb: 1, justifyContent: 'flex-start' }}
          >
            Download Log
          </Button>
        </span>
      </Tooltip>

      {/* 截图 */}
      <Tooltip title="Save graph canvas as PNG">
        <span>
          <Button
            variant="outlined"
            startIcon={<PhotoCameraIcon />}
            onClick={handleScreenshot}
            disabled={!hasData}
            fullWidth
            sx={{ mb: 1, justifyContent: 'flex-start' }}
          >
            Screenshot
          </Button>
        </span>
      </Tooltip>

      {/* 格式提示 */}
      {canExport && (
        <Typography variant="caption" color="text.secondary">
          Formats: {outputFormats.join(', ')}
        </Typography>
      )}
    </Box>
  );
}
