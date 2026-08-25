"use client";
import { useCallback, useMemo, useState } from "react";
import { PostData, api } from "@/lib/api";
import { recordEmojiUsage } from "@/lib/emoji-usage";

export function useReactions(post: PostData, targetId: number) {
  const [localLiked, setLocalLiked] = useState<boolean | undefined>(undefined);
  const [localLikesCount, setLocalLikesCount] = useState<number | undefined>(undefined);
  const [localReactions, setLocalReactions] = useState<Record<string, number> | undefined>(undefined);
  const [myReactionOverride, setMyReactionOverride] = useState<string | null | undefined>(undefined);

  const liked = localLiked !== undefined ? localLiked : post.liked;
  const likesCount = localLikesCount !== undefined ? localLikesCount : post.likes_count;
  const baseReactions = useMemo(() => post.reactions || {}, [post.reactions]);
  const reactions = localReactions !== undefined ? localReactions : baseReactions;
  const myReaction = myReactionOverride !== undefined ? myReactionOverride : (post.my_reaction || null);

  const toggleLike = useCallback(() => {
    const next = !liked;
    setLocalLiked(next);
    setLocalLikesCount(Math.max(0, likesCount + (next ? 1 : -1)));
    (next ? api.like(targetId) : api.unlike(targetId)).catch(() => {
      setLocalLiked(!next);
      setLocalLikesCount(Math.max(0, likesCount + (next ? -1 : 1)));
    });
  }, [liked, likesCount, targetId]);

  const reactTo = useCallback(async (emoji: string) => {
    const next = { ...reactions };
    if (myReaction && myReaction !== emoji) {
      if ((next[myReaction] || 0) <= 1) delete next[myReaction];
      else next[myReaction] -= 1;
    }
    next[emoji] = (next[emoji] || 0) + 1;
    setLocalReactions(next);
    setMyReactionOverride(emoji);
    setLocalLiked(true);
    setLocalLikesCount(myReaction ? likesCount : likesCount + 1);
    recordEmojiUsage(emoji);
    try { await api.react(targetId, emoji); } catch {}
  }, [reactions, myReaction, likesCount, targetId]);

  const unreact = useCallback(async (emoji: string) => {
    const next = { ...reactions };
    if ((next[emoji] || 0) <= 1) delete next[emoji];
    else next[emoji] -= 1;
    setLocalReactions(next);
    setMyReactionOverride(null);
    setLocalLiked(false);
    setLocalLikesCount(Math.max(0, likesCount - 1));
    try { await api.unreact(targetId); } catch {}
  }, [reactions, likesCount, targetId]);

  return { liked, likesCount, reactions, myReaction, toggleLike, reactTo, unreact };
}
