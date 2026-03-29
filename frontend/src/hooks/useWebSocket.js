// ============================================================
// SAGA - WebSocket 连接管理 Hook
// 第 7 批 / 共 10 批
// 用途：管理与后端的 WebSocket 连接，
//       支持指数退避重连、连接状态回调、消息分发
// 关键修复（来自原型机经验）：
//   - 单实例 useRef 防止重复连接
//   - useEffect cleanup 防止内存泄漏
//   - 指数退避 1s→2s→4s→8s→...→30s(max)
// ============================================================

import { useRef, useEffect, useCallback, useState } from 'react';

// 从环境变量读取 WebSocket 地址，不硬编码
// CONFIG: 换机器改 frontend/.env 即可
const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8765';

// 重连参数
const RECONNECT_BASE_MS = 1000;   // 初始重连间隔 1 秒
const RECONNECT_MAX_MS = 30000;   // 最大重连间隔 30 秒
const RECONNECT_FACTOR = 2;       // 退避倍数

/**
 * WebSocket 连接管理 Hook
 *
 * 使用方式：
 *   const { connectionState, send } = useWebSocket(handleMessage);
 *
 * 输入：
 *   onMessage: 消息回调 (parsedData) => void
 *              parsedData 是已解析的 JSON 对象
 * 输出：
 *   connectionState: "connected" | "disconnected" | "reconnecting"
 *   send: (msgObj) => void  发送 JSON 对象到后端
 *   reconnectCountdown: number 重连倒计时秒数（reconnecting 状态时）
 */
export default function useWebSocket(onMessage) {
  const wsRef = useRef(null);           // WebSocket 实例（单实例，防重复连接）
  const reconnectTimer = useRef(null);  // 重连定时器
  const reconnectDelay = useRef(RECONNECT_BASE_MS); // 当前退避间隔
  const mountedRef = useRef(true);      // 组件是否还挂载（防内存泄漏）
  const onMessageRef = useRef(onMessage); // 回调引用（避免闭包陈旧）

  const [connectionState, setConnectionState] = useState('disconnected');
  const [reconnectCountdown, setReconnectCountdown] = useState(0);

  // 保持 onMessage 引用最新（防止闭包捕获旧函数）
  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  // --- 连接函数 ---
  const connect = useCallback(() => {
    // 防止重复连接
    if (wsRef.current && wsRef.current.readyState <= WebSocket.OPEN) {
      return;
    }

    try {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!mountedRef.current) return;
        setConnectionState('connected');
        setReconnectCountdown(0);
        reconnectDelay.current = RECONNECT_BASE_MS; // 重置退避
      };

      ws.onmessage = (event) => {
        if (!mountedRef.current) return;
        try {
          const data = JSON.parse(event.data);
          onMessageRef.current(data);
        } catch (err) {
          console.error('[SAGA WS] 消息解析失败:', err);
        }
      };

      ws.onclose = (event) => {
        if (!mountedRef.current) return;
        wsRef.current = null;
        setConnectionState('reconnecting');
        scheduleReconnect();
      };

      ws.onerror = (err) => {
        console.error('[SAGA WS] 连接错误:', err);
        // onerror 后通常会触发 onclose，在 onclose 中处理重连
      };
    } catch (err) {
      console.error('[SAGA WS] 创建连接失败:', err);
      setConnectionState('reconnecting');
      scheduleReconnect();
    }
  }, []);

  // --- 指数退避重连 ---
  const scheduleReconnect = useCallback(() => {
    if (!mountedRef.current) return;

    const delay = reconnectDelay.current;
    // 倒计时显示
    setReconnectCountdown(Math.ceil(delay / 1000));

    // 倒计时每秒更新
    const countdownInterval = setInterval(() => {
      if (!mountedRef.current) {
        clearInterval(countdownInterval);
        return;
      }
      setReconnectCountdown(prev => {
        if (prev <= 1) {
          clearInterval(countdownInterval);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    reconnectTimer.current = setTimeout(() => {
      clearInterval(countdownInterval);
      if (mountedRef.current) {
        connect();
      }
    }, delay);

    // 指数退避：1s → 2s → 4s → 8s → ... → 30s(max)
    reconnectDelay.current = Math.min(
      delay * RECONNECT_FACTOR,
      RECONNECT_MAX_MS
    );
  }, [connect]);

  // --- 发送消息 ---
  const send = useCallback((msgObj) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msgObj));
    } else {
      console.warn('[SAGA WS] 未连接，消息未发送:', msgObj.type);
    }
  }, []);

  // --- 生命周期：挂载时连接，卸载时清理 ---
  useEffect(() => {
    mountedRef.current = true;
    connect();

    return () => {
      // 清理：防止卸载后仍操作状态
      mountedRef.current = false;
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current);
      }
      if (wsRef.current) {
        wsRef.current.onclose = null; // 阻止触发重连
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect]);

  return { connectionState, send, reconnectCountdown };
}
