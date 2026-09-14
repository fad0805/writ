"use client";
import React from "react";
import { PostData, NovelData, User, EpisodeData } from "@/lib/api";
import MiniPostCard from "./MiniPostCard";
import ClickableCover from "./ClickableCover";
import Icon from "./Icon";
import { hashColor } from "@/lib/avatar";
import { WindowWithGlobals } from "@/lib/windowGlobals";

export type QuotedSeries = { type: "series"; novel: NovelData; author: User };
export type QuotedEpisode = { type: "episode"; episode: EpisodeData; novel: NovelData; author: User };

export default React.memo(function QuotedCard({ quotedPost, quotedSeries, quotedEpisode, hiddenQuoteUrl, onNavigate }: {
  quotedPost: PostData | null;
  quotedSeries: QuotedSeries | null;
  quotedEpisode: QuotedEpisode | null;
  hiddenQuoteUrl: string | null;
  onNavigate: (href: string) => void;
}) {
  return (
    <>
      {hiddenQuoteUrl && (
        <div className="my-8">
          <div className="quoted-series" role="link" onClick={(e) => { e.stopPropagation(); onNavigate(hiddenQuoteUrl); }}>
            <div className="bg-tertiary" style={{ width: 64, height: 64, minWidth: 64, borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <Icon name="block" />
            </div>
            <div className="mini-post-content">
              <div className="mini-post-cw"><Icon name="link" /> 차단/뮤트한 사용자의 글</div>
              <div className="text-sm text-muted">클릭하여 링크로 열기</div>
            </div>
          </div>
        </div>
      )}
      {quotedPost && <div className="my-8"><MiniPostCard post={quotedPost} /></div>}
      {quotedSeries && (
        <div className="quoted-series" onClick={(e) => { e.stopPropagation(); onNavigate(`/series/${quotedSeries.novel.id}`); }}>
            <div className="cover-wrap-64 bg-tertiary">
            {quotedSeries.novel.cover_image ? (
              <ClickableCover src={quotedSeries.novel.cover_image} isSensitive={quotedSeries.novel.is_sensitive} className="cover-img" />
            ) : (
              (window as WindowWithGlobals).__serverLogo ? <img src={(window as WindowWithGlobals).__serverLogo} alt="" className="cover-img" style={{width:64,height:64,objectFit:"contain",padding:8,background:"var(--bg-tertiary)"}} />
              : <div className="cover-fallback cover-fallback-sm" style={{ backgroundColor: hashColor(quotedSeries.novel.title) }}>
                {quotedSeries.novel.title[0]}
              </div>
            )}
          </div>
          <div className="mini-post-content">
            <div className="mini-post-cw"><Icon name="book" /> 시리즈</div>
            <div className="emoji-keyword">{quotedSeries.novel.title}</div>
            {quotedSeries.author && <div className="text-sm text-muted">by {quotedSeries.author.display_name || quotedSeries.author.username}</div>}
            {quotedSeries.novel.description && <div className="text-sm" style={{ color: "var(--text-secondary)", marginTop: 4 }}>{quotedSeries.novel.description.slice(0, 100)}</div>}
          </div>
        </div>
      )}
      {quotedEpisode && (
        <div className="quoted-series" onClick={(e) => { e.stopPropagation(); onNavigate(`/series/${quotedEpisode.novel.id}/episodes/${quotedEpisode.episode.id}`); }}>
          <div className="cover-wrap-64 bg-tertiary">
            {quotedEpisode.novel.cover_image ? (
              <ClickableCover src={quotedEpisode.novel.cover_image} isSensitive={quotedEpisode.novel.is_sensitive} className="cover-img" />
            ) : (
              (window as WindowWithGlobals).__serverLogo ? <img src={(window as WindowWithGlobals).__serverLogo} alt="" className="cover-img" style={{width:64,height:64,objectFit:"contain",padding:8,background:"var(--bg-tertiary)"}} />
              : <div className="cover-fallback cover-fallback-sm" style={{ backgroundColor: hashColor(quotedEpisode.novel.title) }}>
                {quotedEpisode.novel.title[0]}
              </div>
            )}
          </div>
          <div className="mini-post-content">
            <div className="mini-post-cw"><Icon name="book" /> 에피소드</div>
            <div className="emoji-keyword">{quotedEpisode.novel.title} — {quotedEpisode.episode.title}</div>
            {quotedEpisode.author && <div className="text-sm text-muted">by {quotedEpisode.author.display_name || quotedEpisode.author.username}</div>}
            {quotedEpisode.episode.summary ? (
              <div className="text-sm" style={{ color: "var(--text-secondary)", marginTop: 4 }}>{quotedEpisode.episode.summary}</div>
            ) : (
              <div className="text-sm" style={{ color: "var(--text-secondary)", marginTop: 4 }}>{quotedEpisode.episode.content.replace(/\n/g, " ").replace(/<[^>]*>/g, "").slice(0, 50)}{quotedEpisode.episode.content.replace(/\n/g, " ").replace(/<[^>]*>/g, "").length > 50 ? "..." : ""}</div>
            )}
          </div>
        </div>
      )}
    </>
  );
});
