"use client";
import { useEffect, useRef } from "react";

type EventHandler = (data: unknown) => void;

export function useStream(handlers: Record<string, EventHandler>) {
  const handlersRef = useRef(handlers);

  useEffect(() => {
    handlersRef.current = handlers;
  });

  const eventKeys = Object.keys(handlers).sort().join(",");

  useEffect(() => {
    const es = new EventSource("/api/stream");

    for (const event of Object.keys(handlersRef.current)) {
      es.addEventListener(event, (e: MessageEvent) => {
        try {
          const data = JSON.parse(e.data);
          handlersRef.current[event]?.(data);
        } catch {}
      });
    }

    es.onerror = () => {
      es.close();
    };

    return () => {
      es.close();
    };
  }, [eventKeys]);
}
