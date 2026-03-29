// ============================================================
// SAGA - Vite 配置
// 第 7 批 / 共 10 批
// 用途：React 开发服务器和构建配置
//       端口从环境变量读取，不硬编码
// ============================================================

import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    // CONFIG: 端口从命令行或 .env 读取，默认 3000
    port: parseInt(process.env.VITE_PORT || '3000'),
    host: '0.0.0.0', // 允许远程访问（VSCode 端口转发需要）
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
});
