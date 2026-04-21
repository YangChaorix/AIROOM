/* SSE 连接封装 —— 长连接到 /api/stream，推送 agent_output / log / heartbeat。 */
import { useEffect, useRef, useState } from "react";

/**
 * useGlobalStream
 *
 * 用法：
 *   const { events, connected } = useGlobalStream();
 *   // events 是数组，最新在最后；每项 {type, ts, data}
 *
 * 仅处理 "agent_output" / "log" / "heartbeat"；其他事件会被归并到 "unknown"。
 */
export function useGlobalStream({ bufferSize = 200 } = {}) {
  const [events, setEvents] = useState([]);
  const [connected, setConnected] = useState(false);
  const esRef = useRef(null);

  useEffect(() => {
    const es = new EventSource("/api/stream");
    esRef.current = es;

    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);

    const push = (type, evt) => {
      try {
        const data = JSON.parse(evt.data);
        setEvents((prev) => {
          const next = [...prev, { type, ts: Date.now(), data }];
          return next.length > bufferSize ? next.slice(-bufferSize) : next;
        });
      } catch {}
    };

    es.addEventListener("log", (e) => push("log", e));
    es.addEventListener("agent_output", (e) => push("agent_output", e));
    es.addEventListener("heartbeat", () => {}); // 静默心跳

    return () => { es.close(); };
  }, [bufferSize]);

  return { events, connected };
}
