"use client";
import React from "react";
import { LinkPreview } from "@/lib/api";
import { WindowWithGlobals } from "@/lib/windowGlobals";
export default React.memo(function LinkPreviewCard({ lp }: { lp: LinkPreview }) {
  const isLocalLink = (() => { try { return new URL(lp.url).hostname === window.location.hostname; } catch { return false; } })();
  const lpImage = isLocalLink ? ((window as WindowWithGlobals).__serverLogo || lp.image) : lp.image;
  const isVideo = lp.kind === "video";
  return (
    <a href={lp.url} target="_blank" rel="noopener noreferrer" className="link-preview-card" onClick={(e) => e.stopPropagation()} style={{ display: "flex", gap: 12, marginTop: 8, padding: 10, borderRadius: 8, border: "1px solid var(--border)", textDecoration: "none", color: "inherit" }}>
      {lpImage && <img src={lpImage} alt="" style={isVideo ? { width: 120, height: "auto", aspectRatio: "16 / 9", borderRadius: 6, objectFit: "cover", flexShrink: 0 } : { width: 80, height: 80, borderRadius: isLocalLink ? 16 : 6, objectFit: "contain", flexShrink: 0, background: isLocalLink ? "var(--bg-tertiary)" : undefined }} onError={(e) => (e.target as HTMLElement).style.display = "none"} />}
      <div style={{ minWidth: 0 }}>
        <div style={{ fontWeight: 600, fontSize: 14, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{lp.title}</div>
        {lp.description && <div style={{ fontSize: 13, color: "var(--text-secondary)", marginTop: 2, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{lp.description}</div>}
        <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4 }}>{lp.site_name || (() => { try { return new URL(lp.url).hostname; } catch { return ""; } })()}</div>
      </div>
    </a>
  );
});
