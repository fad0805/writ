"use client";
import { useState, useRef, useEffect } from "react";

type Props = {
  src: string;
  onCrop: (blob: Blob) => void;
  onClose: () => void;
  aspectRatio?: number;
};

type Corner = "tl" | "tr" | "bl" | "br";

const MIN_SIZE = 50;

export default function ImageCropper({ src, onCrop, onClose, aspectRatio }: Props) {
  const imgRef = useRef<HTMLImageElement>(null);
  const [imgLoaded, setImgLoaded] = useState(false);
  const [display, setDisplay] = useState({ w: 0, h: 0 });
  const [crop, setCrop] = useState({ x: 0, y: 0, w: 200, h: 200 });
  const drag = useRef<{ mode: "move" | Corner | null; mx: number; my: number; cx: number; cy: number; cw: number; ch: number }>({ mode: null, mx: 0, my: 0, cx: 0, cy: 0, cw: 200, ch: 200 });

  const ar = aspectRatio || 1;

  useEffect(() => {
    const img = new Image();
    img.onload = () => {
      const maxW = Math.min(img.naturalWidth, 460);
      const maxH = Math.min(img.naturalHeight, 400);
      const scale = Math.min(maxW / img.naturalWidth, maxH / img.naturalHeight, 1);
      const w = img.naturalWidth * scale;
      const h = img.naturalHeight * scale;
      let cw = Math.min(w, h * ar) * 0.7;
      let ch = cw / ar;
      if (cw > w) { cw = w; ch = cw / ar; }
      if (ch > h) { ch = h; cw = ch * ar; }
      setDisplay({ w, h });
      setCrop({ x: (w - cw) / 2, y: (h - ch) / 2, w: cw, h: ch });
      setImgLoaded(true);
    };
    img.src = src;
  }, [src, ar]);

  const clampRect = (x: number, y: number, w: number, h: number) => {
    const cw = Math.max(MIN_SIZE, Math.min(display.w, w));
    const ch = Math.max(MIN_SIZE, Math.min(display.h, h));
    return {
      x: Math.max(0, Math.min(display.w - cw, x)),
      y: Math.max(0, Math.min(display.h - ch, y)),
      w: cw,
      h: ch,
    };
  };

  const handleDown = (e: React.PointerEvent, mode: "move" | Corner) => {
    e.preventDefault();
    drag.current = { mode, mx: e.clientX, my: e.clientY, cx: crop.x, cy: crop.y, cw: crop.w, ch: crop.h };
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  };

  const handleMove = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d.mode) return;
    const dx = e.clientX - d.mx;
    const dy = e.clientY - d.my;

    if (d.mode === "move") {
      setCrop(clampRect(d.cx + dx, d.cy + dy, d.cw, d.ch));
      return;
    }

    let nx = d.cx, ny = d.cy, nw = d.cw, nh = d.ch;

    if (d.mode === "br") {
      nw = Math.max(MIN_SIZE, d.cw + dx);
      nh = nw / ar;
    } else if (d.mode === "bl") {
      nw = Math.max(MIN_SIZE, d.cw - dx);
      nh = nw / ar;
      nx = d.cx + d.cw - nw;
    } else if (d.mode === "tr") {
      nh = Math.max(MIN_SIZE, d.ch + dy);
      nw = nh * ar;
      ny = d.cy + d.ch - nh;
    } else if (d.mode === "tl") {
      nw = Math.max(MIN_SIZE, d.cw - dx);
      nh = nw / ar;
      nx = d.cx + d.cw - nw;
      ny = d.cy + d.ch - nh;
    }

    if (nx < 0) { nw = d.cx + d.cw; nx = 0; nh = nw / ar; }
    if (ny < 0) { nh = d.cy + d.ch; ny = 0; nw = nh * ar; }
    nw = Math.min(nw, display.w - nx);
    nh = nw / ar;
    if (nw < MIN_SIZE) { nw = MIN_SIZE; nh = nw / ar; }
    if (nh > display.h - ny) { nh = display.h - ny; nw = nh * ar; }
    if (nw > display.w - nx) { nw = display.w - nx; nh = nw / ar; }

    setCrop(clampRect(nx, ny, nw, nh));
  };

  const handleUp = () => { drag.current.mode = null; };

  const handleConfirm = () => {
    if (!imgRef.current) return;
    const img = imgRef.current;
    const scale = img.naturalWidth / display.w;
    const sx = crop.x * scale;
    const sy = crop.y * scale;
    const sw = crop.w * scale;
    const sh = crop.h * scale;
    const canvas = document.createElement("canvas");
    const outW = Math.round(sw);
    const outH = Math.round(sh);
    canvas.width = outW;
    canvas.height = outH;
    const ctx = canvas.getContext("2d")!;
    ctx.drawImage(img, sx, sy, sw, sh, 0, 0, outW, outH);
    canvas.toBlob((blob) => { if (blob) onCrop(blob); }, "image/jpeg", 0.92);
  };

  const HS = 14;

  return (
    <div className="reply-modal-backdrop active" onClick={onClose}>
      <div className="reply-modal cropper-modal" onClick={(e) => e.stopPropagation()}>
        <h3 className="mb-12">표지 이미지 자르기</h3>
        <div className="cropper-stage">
          {imgLoaded && (
            <img ref={imgRef} src={src} className="cropper-img" style={{ width: display.w, height: display.h }} />
          )}
          {imgLoaded && (
            <div
              className="cropper-overlay"
              style={{
                left: crop.x, top: crop.y,
                width: crop.w, height: crop.h,
              }}
              onPointerDown={(e) => handleDown(e, "move")}
              onPointerMove={handleMove}
              onPointerUp={handleUp}
              onPointerCancel={handleUp}
            >
              <div className="cropper-handle cropper-handle-tl" onPointerDown={(e) => { e.stopPropagation(); handleDown(e, "tl"); }} />
              <div className="cropper-handle cropper-handle-tr" onPointerDown={(e) => { e.stopPropagation(); handleDown(e, "tr"); }} />
              <div className="cropper-handle cropper-handle-bl" onPointerDown={(e) => { e.stopPropagation(); handleDown(e, "bl"); }} />
              <div className="cropper-handle cropper-handle-br" onPointerDown={(e) => { e.stopPropagation(); handleDown(e, "br"); }} />
            </div>
          )}
        </div>
        <p className="text-sm text-muted cropper-hint">
          영역을 드래그하여 위치/크기를 조정하세요
        </p>
        <div className="form-actions cropper-actions">
          <button className="btn btn-primary" onClick={handleConfirm}>적용</button>
          <button className="btn btn-outline" onClick={onClose}>취소</button>
        </div>
      </div>
    </div>
  );
}
