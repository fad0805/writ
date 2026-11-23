"use client";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { api, type AccountCardData, type User } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { getCustomEmojis, renderCustomEmojis, type CustomEmoji } from "@/lib/emojis";
import { sanitizeName, sanitizeSummary } from "@/lib/sanitize";
import Avatar from "@/components/Avatar";
import Icon from "@/components/Icon";

interface CacheEntry {
  data: AccountCardData;
  at: number;
}

interface HoverCardState {
  username: string;
  rect: DOMRect;
  data: AccountCardData | null;
  loading: boolean;
  failed: boolean;
}

const CARD_TTL = 60_000;
const CARD_WIDTH = 320;
const CARD_MAX_HEIGHT = 360;

const cardCache = new Map<string, CacheEntry>();
const pendingCards = new Map<string, Promise<AccountCardData>>();

function cacheKey(username: string): string {
  return username.toLowerCase();
}

function peekCard(username: string): AccountCardData | null {
  const hit = cardCache.get(cacheKey(username));
  if (!hit) return null;
  if (Date.now() - hit.at > CARD_TTL) {
    cardCache.delete(cacheKey(username));
    return null;
  }
  return hit.data;
}

function loadCard(username: string): Promise<AccountCardData> {
  const key = cacheKey(username);
  const cached = peekCard(username);
  if (cached) return Promise.resolve(cached);
  let pending = pendingCards.get(key);
  if (!pending) {
    pending = api.getAccountCard(username)
      .then((data) => {
        cardCache.set(key, { data, at: Date.now() });
        return data;
      })
      .finally(() => pendingCards.delete(key));
    pendingCards.set(key, pending);
  }
  return pending;
}

export function invalidateAccountCard(username?: string): void {
  if (username) cardCache.delete(cacheKey(username));
  else cardCache.clear();
}

/** Extract a local account handle from an anchor href. */
export function accountUsernameFromHref(href: string): string | null {
  if (typeof window === "undefined" || !href) return null;
  let url: URL;
  try {
    url = new URL(href, window.location.href);
  } catch {
    return null;
  }
  if (url.origin !== window.location.origin) return null;
  const path = url.pathname.replace(/\/+$/, "");
  const match = /^\/@([^/]+)$/.exec(path) || /^\/profile\/([^/]+)$/.exec(path);
  if (!match) return null;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return match[1];
  }
}

function positionFor(rect: DOMRect): { left: number; top: number; width: number } {
  const width = Math.min(CARD_WIDTH, window.innerWidth - 16);
  let left = rect.left;
  if (left + width > window.innerWidth - 8) left = window.innerWidth - width - 8;
  if (left < 8) left = 8;

  const below = rect.bottom + 8;
  const above = rect.top - CARD_MAX_HEIGHT - 8;
  const top = below + CARD_MAX_HEIGHT <= window.innerHeight
    ? below
    : above >= 8
      ? above
      : Math.max(8, window.innerHeight - CARD_MAX_HEIGHT - 8);
  return { left, top, width };
}

function FollowButton({ data, canFollow, onUpdate }: {
  data: AccountCardData;
  canFollow: boolean;
  onUpdate: (next: AccountCardData) => void;
}) {
  const [busy, setBusy] = useState(false);
  const profile = data.profile;

  if (!canFollow || data.is_mine) return null;

  const act = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const username = encodeURIComponent(profile.username);
      if (data.has_pending_follower) {
        await fetch(`/api/users/${username}/approve-follow`, { method: "POST", credentials: "include" });
        onUpdate({
          ...data,
          has_pending_follower: false,
          is_following: true,
          is_follow_pending: false,
          followers_count: data.followers_count + 1,
        });
      } else if (data.is_following) {
        await api.unfollow(profile.username);
        onUpdate({
          ...data,
          is_following: false,
          followers_count: Math.max(0, data.followers_count - 1),
        });
      } else {
        await api.follow(profile.username);
        onUpdate({
          ...data,
          is_following: !profile.is_locked,
          is_follow_pending: !!profile.is_locked,
          followers_count: data.followers_count + (profile.is_locked ? 0 : 1),
        });
      }
    } catch {
      // 로그인이 필요하거나 요청이 실패하면 카드 상태를 바꾸지 않는다.
    } finally {
      setBusy(false);
    }
  };

  if (data.am_i_blocked || data.is_blocked) {
    return <span className="account-hover-action account-hover-blocked">차단됨</span>;
  }

  const label = data.has_pending_follower
    ? "수락"
    : data.is_following
      ? "언팔로우"
      : data.is_follow_pending
        ? "요청됨"
        : "팔로우";

  return (
    <button
      type="button"
      className={`btn btn-small btn-follow btn-follow-fixed account-hover-action${
        data.is_following || data.is_follow_pending ? " btn-outline" : " btn-primary"
      }`}
      onClick={(e) => { e.preventDefault(); e.stopPropagation(); void act(); }}
      disabled={busy}
    >
      {label}
    </button>
  );
}

function AccountHoverCardContent({ state, emojis, canFollow, onUpdate }: {
  state: HoverCardState;
  emojis: CustomEmoji[];
  canFollow: boolean;
  onUpdate: (next: AccountCardData) => void;
}) {
  const data = state.data;
  if (state.failed || (!state.loading && !data)) {
    return (
      <div className="account-hover-error">
        계정 정보를 불러오지 못했습니다.
      </div>
    );
  }
  if (!data) {
    return (
      <div className="account-hover-loading">
        <div className="account-hover-skeleton-avatar" />
        <div className="account-hover-skeleton-lines"><i /><i /><i /></div>
      </div>
    );
  }

  const profile: User = data.profile;
  const displayName = profile.display_name || profile.username;
  const roleIcon = profile.role === "owner" ? "books_solid" : profile.role === "admin" ? "shield_filled" : profile.role === "moderator" ? "shield_filled" : null;
  const roleColor = profile.role === "owner" ? "var(--accent)" : profile.role === "admin" ? "#27ae60" : "#cc8800";
  const roleTitle = profile.role === "owner" ? "오너" : profile.role === "admin" ? "관리자" : "조율자";

  return (
    <>
      {profile.header && (
        <div className="account-hover-header" style={{ backgroundImage: `url("${profile.header.replace(/"/g, "%22")}")` }} />
      )}
      <div className={`account-hover-body${profile.header ? " with-header" : ""}`}>
        <div className="account-hover-top">
          <Link href={`/@${encodeURIComponent(profile.username)}`} className="account-hover-avatar-link" data-no-account-hover>
            <Avatar user={profile} className="account-hover-avatar" />
          </Link>
          <FollowButton data={data} canFollow={canFollow} onUpdate={onUpdate} />
        </div>
        <Link href={`/@${encodeURIComponent(profile.username)}`} className="account-hover-name" data-no-account-hover>
          <span dangerouslySetInnerHTML={{ __html: sanitizeName(renderCustomEmojis(displayName, emojis, 15)) }} />
          {profile.is_locked && <Icon name="lock_filled" className="account-hover-lock" />}
          {roleIcon && (data.is_mine || profile.show_badge) && (
            <Icon name={roleIcon} style={{ color: roleColor, fontSize: "0.7em", verticalAlign: "middle", marginLeft: 3 }} title={roleTitle} />
          )}
        </Link>
        <div className="account-hover-handle">@{profile.display_handle || profile.username}</div>
        {profile.summary && (
          <div
            className="account-hover-bio"
            dangerouslySetInnerHTML={{ __html: sanitizeSummary(renderCustomEmojis(profile.summary.replace(/\n/g, "<br>"), emojis, 14)) }}
          />
        )}
        <div className="account-hover-stats">
          <span><strong>{data.total_posts.toLocaleString()}</strong> 게시물</span>
          <span><strong>{data.followers_count.toLocaleString()}</strong> 팔로워</span>
          <span><strong>{data.following_count.toLocaleString()}</strong> 팔로잉</span>
        </div>
        {data.is_follower && <div className="account-hover-note">당신을 팔로우합니다</div>}
        {profile.moved_to && (
          <div className="account-hover-note">
            이 계정은 <Link href={`/@${encodeURIComponent(profile.moved_to)}`} data-no-account-hover>@{profile.moved_to}</Link>(으)로 이전했습니다.
          </div>
        )}
      </div>
    </>
  );
}

export default function AccountHoverCard() {
  const { user: currentUser, loading: authLoading } = useAuth();
  const [state, setState] = useState<HoverCardState | null>(null);
  const [emojis, setEmojis] = useState<CustomEmoji[]>([]);
  const cardRef = useRef<HTMLDivElement | null>(null);
  const anchorRef = useRef<HTMLAnchorElement | null>(null);
  const overAnchorRef = useRef(false);
  const overCardRef = useRef(false);
  const hideTimerRef = useRef<number | null>(null);

  useEffect(() => {
    getCustomEmojis().then(setEmojis);
    const handler = (e: Event) => setEmojis((e as CustomEvent<CustomEmoji[]>).detail || []);
    window.addEventListener("emojichange", handler);
    return () => window.removeEventListener("emojichange", handler);
  }, []);

  const clearHideTimer = useCallback(() => {
    if (hideTimerRef.current !== null) {
      window.clearTimeout(hideTimerRef.current);
      hideTimerRef.current = null;
    }
  }, []);

  const hide = useCallback(() => {
    clearHideTimer();
    anchorRef.current = null;
    overAnchorRef.current = false;
    overCardRef.current = false;
    setState(null);
  }, [clearHideTimer]);

  const scheduleHide = useCallback(() => {
    clearHideTimer();
    hideTimerRef.current = window.setTimeout(() => {
      if (!overAnchorRef.current && !overCardRef.current) hide();
    }, 220);
  }, [clearHideTimer, hide]);

  const showForAnchor = useCallback((anchor: HTMLAnchorElement) => {
    const username = accountUsernameFromHref(anchor.getAttribute("href") || "");
    if (!username) return;
    if (anchorRef.current === anchor && state?.username.toLowerCase() === username.toLowerCase()) {
      overAnchorRef.current = true;
      return;
    }
    clearHideTimer();
    anchorRef.current = anchor;
    overAnchorRef.current = true;
    overCardRef.current = false;
    const cached = peekCard(username);
    setState({
      username,
      rect: anchor.getBoundingClientRect(),
      data: cached,
      loading: !cached,
      failed: false,
    });
    if (cached) return;
    loadCard(username)
      .then((data) => {
        if (anchorRef.current !== anchor) return;
        if (!overAnchorRef.current && !overCardRef.current) return;
        setState((prev) => prev && prev.username.toLowerCase() === username.toLowerCase()
          ? { ...prev, data, loading: false, failed: false }
          : prev);
      })
      .catch(() => {
        if (anchorRef.current !== anchor) return;
        setState((prev) => prev && prev.username.toLowerCase() === username.toLowerCase()
          ? { ...prev, loading: false, failed: true }
          : prev);
      });
  }, [clearHideTimer, state?.username]);

  useEffect(() => {
    const onPointerOver = (e: PointerEvent) => {
      if (e.pointerType === "touch") return;
      const target = e.target as HTMLElement | null;
      const anchor = target?.closest?.("a") as HTMLAnchorElement | null;
      if (!anchor || anchor.closest(".account-hover-card") || anchor.hasAttribute("data-no-account-hover")) return;
      showForAnchor(anchor);
    };

    const onPointerOut = (e: PointerEvent) => {
      const anchor = anchorRef.current;
      if (!anchor) return;
      const related = e.relatedTarget as Node | null;
      if (related && anchor.contains(related)) return;
      if (related && cardRef.current?.contains(related)) {
        overAnchorRef.current = false;
        clearHideTimer();
        return;
      }
      if (e.target instanceof Node && anchor.contains(e.target)) {
        overAnchorRef.current = false;
        scheduleHide();
      }
    };

    const onFocusIn = (e: FocusEvent) => {
      const target = e.target as HTMLElement | null;
      const anchor = target?.closest?.("a") as HTMLAnchorElement | null;
      if (!anchor || anchor.closest(".account-hover-card") || anchor.hasAttribute("data-no-account-hover")) return;
      showForAnchor(anchor);
    };

    const onFocusOut = (e: FocusEvent) => {
      const anchor = anchorRef.current;
      if (!anchor) return;
      const related = e.relatedTarget as Node | null;
      if (related && (anchor.contains(related) || cardRef.current?.contains(related))) return;
      overAnchorRef.current = false;
      scheduleHide();
    };

    const onClick = (e: MouseEvent) => {
      if (cardRef.current?.contains(e.target as Node)) return;
      hide();
    };
    const onKeyDown = (e: KeyboardEvent) => { if (e.key === "Escape") hide(); };

    document.addEventListener("pointerover", onPointerOver);
    document.addEventListener("pointerout", onPointerOut);
    document.addEventListener("focusin", onFocusIn);
    document.addEventListener("focusout", onFocusOut);
    document.addEventListener("click", onClick);
    document.addEventListener("keydown", onKeyDown);
    window.addEventListener("scroll", hide, true);
    window.addEventListener("resize", hide);
    return () => {
      document.removeEventListener("pointerover", onPointerOver);
      document.removeEventListener("pointerout", onPointerOut);
      document.removeEventListener("focusin", onFocusIn);
      document.removeEventListener("focusout", onFocusOut);
      document.removeEventListener("click", onClick);
      document.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("scroll", hide, true);
      window.removeEventListener("resize", hide);
    };
  }, [clearHideTimer, hide, scheduleHide, showForAnchor]);

  const updateCard = useCallback((next: AccountCardData) => {
    cardCache.set(cacheKey(next.profile.username), { data: next, at: Date.now() });
    setState((prev) => prev && prev.username.toLowerCase() === next.profile.username.toLowerCase()
      ? { ...prev, data: next, loading: false, failed: false }
      : prev);
    window.dispatchEvent(new CustomEvent("account-card-follow-change", {
      detail: { username: next.profile.username, isFollowing: next.is_following, followersCount: next.followers_count },
    }));
  }, []);

  const position = useMemo(() => state ? positionFor(state.rect) : null, [state]);
  if (!state || !position || typeof document === "undefined") return null;

  return createPortal(
    <div
      ref={cardRef}
      className="account-hover-card"
      style={{ left: position.left, top: position.top, width: position.width }}
      role="tooltip"
      data-no-account-hover
      onPointerEnter={() => { overCardRef.current = true; clearHideTimer(); }}
      onPointerLeave={(e) => {
        overCardRef.current = false;
        const related = e.relatedTarget as Node | null;
        if (related && anchorRef.current?.contains(related)) return;
        scheduleHide();
      }}
      onFocusCapture={() => { overCardRef.current = true; clearHideTimer(); }}
      onBlurCapture={(e) => {
        const related = e.relatedTarget as Node | null;
        if (related && cardRef.current?.contains(related)) return;
        overCardRef.current = false;
        scheduleHide();
      }}
    >
      <AccountHoverCardContent
        state={state}
        emojis={emojis}
        canFollow={!authLoading && !!currentUser}
        onUpdate={updateCard}
      />
    </div>,
    document.body,
  );
}
