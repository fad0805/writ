"use client";
import { useState, useEffect, useRef, useCallback } from "react";

export type ViewerMedia = { url: string; type?: string; alt?: string };

export default function MediaViewer({ media, index, onIndexChange, onClose }: {
  media: ViewerMedia[];
  index: number;
  onIndexChange: (i: number) => void;
  onClose: () => void;
}) {
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const lastTouchDist = useRef(0);
  const lastTouchCenter = useRef({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const panStart = useRef({ x: 0, y: 0 });
  const panOrigin = useRef({ x: 0, y: 0 });
  const swipeStartX = useRef(0);
  const prevIndex = useRef(-1);
  const closingFromPop = useRef(false);

  const closeViewer = useCallback(() => {
    // popstate(브라우저 뒤로가기)에서 호출됐다면 이미 onClose를 호출한 상태이므로
    // history.back()을 다시 실행하지 않는다. X/백드롭 클릭은 pushState로 남긴
    // 히스토리를 되돌리고, popstate 핸들러(onPop)가 onClose를 단 한 번 호출한다.
    if (closingFromPop.current) {
      closingFromPop.current = false;
      onClose();
      return;
    }
    history.back();
  }, [onClose]);

  useEffect(() => {
    const wasOpen = prevIndex.current >= 0;
    const isOpen = index >= 0;
    prevIndex.current = index;
    if (!wasOpen && isOpen) {
      history.pushState({ viewer: true }, "");
    }
    if (!isOpen) return;
    const resetId = setTimeout(() => {
      setZoom(1);
      setPan({ x: 0, y: 0 });
    }, 0);
    const onPop = () => {
      closingFromPop.current = true;
      onClose();
    };
    window.addEventListener("popstate", onPop);
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeViewer();
      else if (e.key === "ArrowLeft" && index > 0) onIndexChange(index - 1);
      else if (e.key === "ArrowRight" && index < media.length - 1) onIndexChange(index + 1);
    };
    window.addEventListener("keydown", handler);
    return () => { clearTimeout(resetId); window.removeEventListener("keydown", handler); window.removeEventListener("popstate", onPop); };
  }, [index, media.length, onClose, onIndexChange, closeViewer]);

  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const delta = e.deltaY > 0 ? -0.15 : 0.15;
    setZoom((z) => Math.min(5, Math.max(0.5, z + delta)));
  }, []);

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    if (e.touches.length === 2) {
      e.preventDefault();
      const dx = e.touches[0].clientX - e.touches[1].clientX;
      const dy = e.touches[0].clientY - e.touches[1].clientY;
      lastTouchDist.current = Math.hypot(dx, dy);
      lastTouchCenter.current = {
        x: (e.touches[0].clientX + e.touches[1].clientX) / 2,
        y: (e.touches[0].clientY + e.touches[1].clientY) / 2,
      };
    } else if (e.touches.length === 1 && zoom > 1) {
      setIsPanning(true);
      panStart.current = { x: e.touches[0].clientX, y: e.touches[0].clientY };
      panOrigin.current = { ...pan };
    } else if (e.touches.length === 1) {
      swipeStartX.current = e.touches[0].clientX;
    }
  }, [zoom, pan]);

  const handleTouchMove = useCallback((e: React.TouchEvent) => {
    if (e.touches.length === 2) {
      e.preventDefault();
      const dx = e.touches[0].clientX - e.touches[1].clientX;
      const dy = e.touches[0].clientY - e.touches[1].clientY;
      const dist = Math.hypot(dx, dy);
      if (lastTouchDist.current > 0) {
        const scale = dist / lastTouchDist.current;
        setZoom((z) => Math.min(5, Math.max(0.5, z * scale)));
      }
      lastTouchDist.current = dist;
    } else if (e.touches.length === 1 && isPanning) {
      e.preventDefault();
      const dx = e.touches[0].clientX - panStart.current.x;
      const dy = e.touches[0].clientY - panStart.current.y;
      setPan({ x: panOrigin.current.x + dx, y: panOrigin.current.y + dy });
    }
  }, []);

  const handleTouchEnd = useCallback((e: React.TouchEvent) => {
    if (swipeStartX.current !== 0 && zoom <= 1) {
      const dx = e.changedTouches[0].clientX - swipeStartX.current;
      if (Math.abs(dx) > 60) {
        if (dx > 0 && index > 0) onIndexChange(index - 1);
        else if (dx < 0 && index < media.length - 1) onIndexChange(index + 1);
      }
    }
    swipeStartX.current = 0;
    lastTouchDist.current = 0;
    setIsPanning(false);
  }, [zoom, index, media.length, onIndexChange]);

  const handleDblClick = useCallback(() => {
    setZoom((z) => {
      if (z > 1) { setPan({ x: 0, y: 0 }); return 1; }
      return 2;
    });
  }, []);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (zoom > 1) {
      setIsPanning(true);
      panStart.current = { x: e.clientX, y: e.clientY };
      panOrigin.current = { ...pan };
      e.preventDefault();
    }
  }, [zoom, pan]);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (isPanning) {
      const dx = e.clientX - panStart.current.x;
      const dy = e.clientY - panStart.current.y;
      setPan({ x: panOrigin.current.x + dx, y: panOrigin.current.y + dy });
    }
  }, []);

  const handleMouseUp = useCallback(() => { setIsPanning(false); }, []);

  if (index < 0 || !media[index]) return null;
  const m = media[index];
  return (
    <div className="reply-modal-backdrop active" onClick={closeViewer} style={{ zIndex: 2000 }}>
      <div className="media-viewer" onClick={(e) => e.stopPropagation()} style={{ maxWidth: "90vw", maxHeight: "90vh", display: "flex", alignItems: "center", justifyContent: "center", position: "relative", overflow: "hidden", cursor: zoom > 1 ? "grab" : "default", touchAction: "none" }}
        onWheel={handleWheel}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        {index > 0 && (
          <button onClick={(e) => { e.stopPropagation(); onIndexChange(index - 1); }} style={{ position: "absolute", left: 8, top: "50%", transform: "translateY(-50%)", background: "rgba(0,0,0,0.5)", border: "none", borderRadius: "50%", width: 40, height: 40, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", zIndex: 10, fontSize: 20, color: "#fff" }}>‹</button>
        )}
        {index < media.length - 1 && (
          <button onClick={(e) => { e.stopPropagation(); onIndexChange(index + 1); }} style={{ position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)", background: "rgba(0,0,0,0.5)", border: "none", borderRadius: "50%", width: 40, height: 40, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", zIndex: 10, fontSize: 20, color: "#fff" }}>›</button>
        )}
        <button onClick={(e) => { e.stopPropagation(); closeViewer(); }} style={{ position: "absolute", top: 8, right: 8, background: "rgba(0,0,0,0.5)", border: "none", borderRadius: "50%", width: 36, height: 36, display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontSize: 22, cursor: "pointer", zIndex: 10 }}>×</button>
        {zoom > 1 && <div style={{ position: "absolute", top: 8, left: 8, background: "rgba(0,0,0,0.5)", color: "#fff", borderRadius: 12, padding: "2px 10px", fontSize: 12, zIndex: 10, userSelect: "none" }}>{Math.round(zoom * 100)}%</div>}
        {m.type === "video" ? (
          <video src={m.url} controls style={{ maxWidth: "100%", maxHeight: "85vh", borderRadius: 8 }} />
        ) : (
          <img src={m.url} alt={m.alt || ""} draggable={false} onDoubleClick={handleDblClick} style={{ maxWidth: zoom > 1 ? "none" : "100%", maxHeight: zoom > 1 ? "none" : "85vh", borderRadius: zoom > 1 ? 0 : 8, objectFit: "contain", transform: `scale(${zoom}) translate(${pan.x / zoom}px, ${pan.y / zoom}px)`, transition: isPanning ? "none" : "transform 0.15s ease", userSelect: "none" }} />
        )}
      </div>
    </div>
  );
}
