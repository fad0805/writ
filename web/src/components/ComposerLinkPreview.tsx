"use client";
import MiniPostCard from "./MiniPostCard";
import { PostData } from "@/lib/api";

export default function ComposerLinkPreview({ quotePost, quoteUrl, linkPreview, linkPreviewLoading, onClearQuote, onClearPreview }: {
  quotePost: PostData | null;
  quoteUrl: string;
  linkPreview: { url: string; title: string; description: string; image: string } | null;
  linkPreviewLoading: boolean;
  onClearQuote: () => void;
  onClearPreview: () => void;
}) {
  return (
    <>
      {(quotePost || quoteUrl) && (
        <div style={{ marginBottom: 8, padding: 10, borderRadius: 8, border: "1px solid var(--border)", background: "var(--bg-tertiary)", position: "relative" }}>
          {quotePost ? (
            <MiniPostCard post={quotePost} />
          ) : (
            <div style={{ fontSize: 13, color: "var(--text-muted)" }}>게시글 불러오는 중...</div>
          )}
          <button type="button" onClick={onClearQuote} style={{ position: "absolute", top: 4, right: 4, background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer", fontSize: 14, lineHeight: 1, zIndex: 2 }}>×</button>
        </div>
      )}
      {(linkPreview || linkPreviewLoading) && !quoteUrl && (
        <div style={{ marginBottom: 8, padding: 10, borderRadius: 8, border: "1px solid var(--border)", background: "var(--bg-tertiary)", display: "flex", gap: 10, alignItems: "flex-start", position: "relative" }}>
          {linkPreviewLoading && !linkPreview ? (
            <div style={{ fontSize: 13, color: "var(--text-muted)" }}>링크 미리보기 불러오는 중...</div>
          ) : linkPreview && (
            <>
              {linkPreview.image && <img src={linkPreview.image} alt="" style={{ width: 60, height: 60, borderRadius: 6, objectFit: "cover", flexShrink: 0 }} onError={(e) => (e.target as HTMLElement).style.display = "none"} />}
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontWeight: 600, fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{linkPreview.title}</div>
                {linkPreview.description && <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 2, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{linkPreview.description}</div>}
                <a href={linkPreview.url} target="_blank" rel="noopener noreferrer" style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 3, textDecoration: "none" }}>{(() => { try { return new URL(linkPreview.url).hostname; } catch { return ""; } })()}</a>
              </div>
              <button type="button" onClick={onClearPreview} style={{ position: "absolute", top: 4, right: 4, background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer", fontSize: 14, lineHeight: 1 }}>×</button>
            </>
          )}
        </div>
      )}
    </>
  );
}
