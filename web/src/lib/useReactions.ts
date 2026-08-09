"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { PostData, api } from "@/lib/api";
import { recordEmojiUsage } from "@/lib/emoji-usage";

export function useReactions(post: PostData, targetId: number) {
  const [liked, setLiked] = useState(post.liked);
  const [likesCount, setLikesCount] = useState(post.likes_count);
  const [reactions, setReactions] = useState<Record<string, number>>(post.reactions || {});
  const [myReactionOverride, setMyReactionOverride] = useState<string | null | undefined>(undefined);
  const myReaction = myReactionOverride !== undefined ? myReactionOverride : (post.my_reaction || null);

  const postIdRef = useRef(post.id);
  useEffect(() => {
    if (postIdRef.current !== post.id) {
      postIdRef.current = post.id;
      setLiked(post.liked);
      setLikesCount(post.likes_count);
      setReactions(post.reactions || {});
      setMyReactionOverride(post.my_reaction || null);
    }
  }, [post.id, post.liked, post.likes_count, post.reactions, post.my_reaction]);
  useEffect(() => {
    setReactions(post.reactions || {});
  }, [post.reactions]);
  useEffect(() => {
    setLikesCount(post.likes_count);
  }, [post.likes_count]);

  const toggleLike = useCallback(() => {
    const next = !liked;
    setLiked(next);
    setLikesCount(Math.max(0, likesCount + (next ? 1 : -1)));
    (next ? api.like(targetId) : api.unlike(targetId)).catch(() => {
      setLiked(!next);
      setLikesCount(Math.max(0, likesCount + (next ? -1 : 1)));
    });
  }, [liked, likesCount, targetId]);

  const reactTo = useCallback(async (emoji: string) => {
    const next = { ...reactions };
    if (myReaction && myReaction !== emoji) {
      if ((next[myReaction] || 0) <= 1) delete next[myReaction];
      else next[myReaction] -= 1;
    }
    next[emoji] = (next[emoji] || 0) + 1;
    setReactions(next);
    setMyReactionOverride(emoji);
    setLiked(true);
    setLikesCount(myReaction ? likesCount : likesCount + 1);
    recordEmojiUsage(emoji);
    try { await api.react(targetId, emoji); } catch {}
  }, [reactions, myReaction, likesCount, targetId]);

  const unreact = useCallback(async (emoji: string) => {
    const next = { ...reactions };
    if (next[emoji] <= 1) delete next[emoji];
    else next[emoji] -= 1;
    setReactions(next);
    setMyReactionOverride(null);
    setLiked(false);
    setLikesCount(Math.max(0, likesCount - 1));
    try { await api.unreact(targetId); } catch {}
  }, [reactions, likesCount, targetId]);

  return { liked, likesCount, reactions, myReaction, toggleLike, reactTo, unreact };
}
