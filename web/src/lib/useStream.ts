"use client";
import { useEffect, useRef, useCallback } from "react";

type EventHandler = (data: any) => void;

export function useStream(handlers: Record<string, EventHandler>) {
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  useEffect(() => {
    const es = new EventSource("/api/stream");
    const registered: string[] = [];

    for (const event of Object.keys(handlers)) {
      es.addEventListener(event, (e: MessageEvent) => {
        try {
          const data = JSON.parse(e.data);
          handlersRef.current[event]?.(data);
        } catch {}
      });
      registered.push(event);
    }

    es.onerror = () => {
      es.close();
    };

    return () => {
      es.close();
    };
  }, []);
}
