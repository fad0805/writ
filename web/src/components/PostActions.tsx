"use client";
import React from "react";
import { PostData, User } from "@/lib/api";
import Icon from "./Icon";
import EmojiPicker from "./EmojiPicker";
import ShareButton from "@/components/ShareButton";

export default React.memo(function PostActions({ post, currentUser, liked, likesCount, myReaction, boosted, boostsCount, bookmarked, pinned, showMoreActions, remoteUrl, onReply, onToggleLike, onToggleBoost, onToggleBookmark, onReact, onToggleMore, onTogglePin, onEdit, onRewrite, onDelete, onReport }: {
  post: PostData;
  currentUser: User | null;
  liked: boolean;
  likesCount: number;
  myReaction: string | null;
  boosted: boolean;
  boostsCount: number;
  bookmarked: boolean;
  pinned: boolean;
  showMoreActions: boolean;
  remoteUrl: string;
  onReply: () => void;
  onToggleLike: () => void;
  onToggleBoost: () => void;
  onToggleBookmark: () => void;
  onReact: (emoji: string) => void;
  onToggleMore: () => void;
  onTogglePin: () => void;
  onEdit: () => void;
  onRewrite: () => void;
  onDelete: () => void;
  onReport: () => void;
}) {
  const canBoost = !boosted && (post.visibility === "mention" || (!post.is_mine && post.visibility === "followers"));
  const moreActionsVisible = post.is_mine || currentUser?.is_admin || (currentUser && !post.is_mine);

  return (
    <div className="post-actions" onClick={(e) => e.stopPropagation()}>
      <button onClick={onReply} className="action-btn">
        <Icon name="reply" /> {typeof post.replies_count === "number" ? post.replies_count : 0}
      </button>
      <form className="inline-form" onSubmit={(e) => e.preventDefault()}>
        <button type="button" onClick={onToggleBoost} disabled={canBoost} className={`action-btn ${boosted ? "boosted" : ""}`}>
          <Icon name="refresh" /> {typeof boostsCount === "number" ? boostsCount : 0}
        </button>
      </form>
      {currentUser?.enable_reactions !== false ? (
        <span onClick={(e) => e.stopPropagation()} className="relative-wrap" style={{ marginBottom: -2 }}>
          <EmojiPicker onEmoji={onReact} />
        </span>
      ) : (
        <form className="inline-form" onSubmit={(e) => e.preventDefault()}>
          <button type="button" onClick={onToggleLike} className={`action-btn ${liked ? "liked" : ""}`}>
            <Icon name={myReaction && liked ? "star_filled" : liked ? "star_filled" : "star"} /> {typeof likesCount === "number" ? likesCount : 0}
          </button>
        </form>
      )}
      <button onClick={(e) => { e.stopPropagation(); onToggleBookmark(); }} className={`action-btn${bookmarked ? " bookmarked" : ""}`} style={{ color: bookmarked ? "#5b7db5" : undefined }}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill={bookmarked ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>
      </button>
      {moreActionsVisible && (
        <div className="post-actions-more" onClick={(e) => e.stopPropagation()}>
          <button onClick={onToggleMore} className="action-btn post-actions-more-btn">
            <Icon name="more_horizontal" />
          </button>
          {showMoreActions && (
            <div className="post-actions-dropdown">
              <ShareButton url={post.author?.username?.includes('@') && remoteUrl ? remoteUrl : (post.number ? `/@${post.author.username}/${post.number}` : `/post/${post.id}`)} className="post-actions-dropdown-item" />
              {post.is_mine && post.visibility !== "mention" && (
                <button onClick={() => { onToggleMore(); onTogglePin(); }} className="post-actions-dropdown-item">
                  <Icon name={pinned ? "pin_filled" : "pin"} /> {pinned ? "고정 해제" : "고정"}
                </button>
              )}
              {post.is_mine && (
                <button onClick={() => { onToggleMore(); onEdit(); }} className="post-actions-dropdown-item">
                  <Icon name="edit" /> 수정
                </button>
              )}
              {post.is_mine && (
                <button onClick={() => { onToggleMore(); onRewrite(); }} className="post-actions-dropdown-item">
                  <Icon name="trash" /> 지우고 다시 쓰기
                </button>
              )}
              {(post.is_mine || currentUser?.is_admin) && (
                <button onClick={() => { onToggleMore(); onDelete(); }} className="post-actions-dropdown-item post-actions-dropdown-danger">
                  <Icon name="trash" /> 삭제
                </button>
              )}
              {currentUser && !post.is_mine && (
                <button onClick={() => { onToggleMore(); onReport(); }} className="post-actions-dropdown-item">
                  <Icon name="flag" /> 신고
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
});
