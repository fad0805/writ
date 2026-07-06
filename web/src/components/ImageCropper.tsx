"use client";
import { useState, useRef, useEffect } from "react";

type Props = {
  src: string;
  onCrop: (blob: Blob) => void;
  onClose: () => void;
};

type Corner = "tl" | "tr" | "bl" | "br";

const MIN_SIZE = 50;

export default function ImageCropper({ src, onCrop, onClose }: Props) {
  const imgRef = useRef<HTMLImageElement>(null);
  const [imgLoaded, setImgLoaded] = useState(false);
  const [display, setDisplay] = useState({ w: 0, h: 0 });
  const [crop, setCrop] = useState({ x: 0, y: 0, size: 200 });
  const drag = useRef<{ mode: "move" | Corner | null; mx: number; my: number; cx: number; cy: number; cs: number }>({ mode: null, mx: 0, my: 0, cx: 0, cy: 0, cs: 200 });

  useEffect(() => {
    const img = new Image();
    img.onload = () => {
      const maxW = Math.min(img.naturalWidth, 460);
      const maxH = Math.min(img.naturalHeight, 400);
      const scale = Math.min(maxW / img.naturalWidth, maxH / img.naturalHeight, 1);
      const w = img.naturalWidth * scale;
      const h = img.naturalHeight * scale;
      const s = Math.min(w, h) * 0.7;
      setDisplay({ w, h });
      setCrop({ x: (w - s) / 2, y: (h - s) / 2, size: s });
      setImgLoaded(true);
    };
    img.src = src;
  }, [src]);

  const clampRect = (x: number, y: number, size: number) => {
    const sz = Math.max(MIN_SIZE, size);
    return {
      x: Math.max(0, Math.min(display.w - sz, x)),
      y: Math.max(0, Math.min(display.h - sz, y)),
      size: sz,
    };
  };

  const handleDown = (e: React.PointerEvent, mode: "move" | Corner) => {
    e.preventDefault();
    drag.current = { mode, mx: e.clientX, my: e.clientY, cx: crop.x, cy: crop.y, cs: crop.size };
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  };

  const handleMove = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d.mode) return;
    const dx = e.clientX - d.mx;
    const dy = e.clientY - d.my;

    if (d.mode === "move") {
      setCrop(clampRect(d.cx + dx, d.cy + dy, d.cs));
      return;
    }

    let ns = d.cs;
    if (d.mode === "br") ns = d.cs + dx;
    else if (d.mode === "bl") ns = d.cs - dx;
    else if (d.mode === "tr") ns = d.cs + dx;
    else if (d.mode === "tl") ns = d.cs - dx;

    ns = Math.max(MIN_SIZE, ns);
    const right = d.cx + d.cs;
    const bottom = d.cy + d.cs;

    let nx = d.cx, ny = d.cy;
    if (d.mode === "bl" || d.mode === "tl") nx = right - ns;
    if (d.mode === "tr" || d.mode === "tl") ny = bottom - ns;
    if (nx < 0) { nx = 0; ns = right; }
    if (ny < 0) { ny = 0; ns = bottom; }
    ns = Math.min(ns, display.w - nx, display.h - ny);
    setCrop(clampRect(nx, ny, ns));
  };

  const handleUp = () => { drag.current.mode = null; };

  const handleConfirm = () => {
    if (!imgRef.current) return;
    const img = imgRef.current;
    const scale = img.naturalWidth / display.w;
    const sx = crop.x * scale;
    const sy = crop.y * scale;
    const s = crop.size * scale;
    const canvas = document.createElement("canvas");
    canvas.width = s;
    canvas.height = s;
    const ctx = canvas.getContext("2d")!;
    ctx.drawImage(img, sx, sy, s, s, 0, 0, s, s);
    canvas.toBlob((blob) => { if (blob) onCrop(blob); }, "image/jpeg", 0.92);
  };

  const s = crop.size;
  const HS = 14;

  return (
    <div className="reply-modal-backdrop active" onClick={onClose}>
      <div className="reply-modal cropper-modal">
        <h3 className="mb-12">프로필 사진 자르기</h3>
        <div style={{ position: "relative", display: "inline-block", borderRadius: 8, overflow: "hidden", lineHeight: 0, touchAction: "none", userSelect: "none" }}>
          {imgLoaded && (
            <img ref={imgRef} src={src} style={{ width: display.w, height: display.h, display: "block" }} />
          )}
          {imgLoaded && (
            <div
              style={{
                position: "absolute", left: crop.x, top: crop.y,
                width: s, height: s,
                boxShadow: "0 0 0 9999px rgba(0,0,0,0.5)",
                border: "2px solid #fff",
                cursor: "move",
              }}
              onPointerDown={(e) => handleDown(e, "move")}
              onPointerMove={handleMove}
              onPointerUp={handleUp}
              onPointerCancel={handleUp}
            >
              <div style={{ position: "absolute", top: -HS/2, left: -HS/2, width: HS, height: HS, cursor: "nwse-resize", background: "#fff", borderRadius: "50%", border: "2px solid #333" }} onPointerDown={(e) => { e.stopPropagation(); handleDown(e, "tl"); }} />
              <div style={{ position: "absolute", top: -HS/2, right: -HS/2, width: HS, height: HS, cursor: "nesw-resize", background: "#fff", borderRadius: "50%", border: "2px solid #333" }} onPointerDown={(e) => { e.stopPropagation(); handleDown(e, "tr"); }} />
              <div style={{ position: "absolute", bottom: -HS/2, left: -HS/2, width: HS, height: HS, cursor: "nesw-resize", background: "#fff", borderRadius: "50%", border: "2px solid #333" }} onPointerDown={(e) => { e.stopPropagation(); handleDown(e, "bl"); }} />
              <div style={{ position: "absolute", bottom: -HS/2, right: -HS/2, width: HS, height: HS, cursor: "nwse-resize", background: "#fff", borderRadius: "50%", border: "2px solid #333" }} onPointerDown={(e) => { e.stopPropagation(); handleDown(e, "br"); }} />
            </div>
          )}
        </div>
        <p className="text-sm text-muted" style={{ margin: "8px 0 0" }}>
          영역을 드래그하여 위치/크기를 조정하세요
        </p>
        <div className="form-actions" style={{ justifyContent: "center" }}>
          <button className="btn btn-primary" onClick={handleConfirm}>적용</button>
          <button className="btn btn-outline" onClick={onClose}>취소</button>
        </div>
      </div>
    </div>
  );
}
