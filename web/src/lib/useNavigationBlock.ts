"use client";
import { useCallback, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";

export function useNavigationBlock(active: boolean) {
  const router = useRouter();
  const activeRef = useRef(active);
  const navigatingRef = useRef(false);
  const resetTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    activeRef.current = active;
  }, [active]);

  const suppress = useCallback(() => {
    activeRef.current = false;
    navigatingRef.current = true;
  }, []);

  const markNavigating = useCallback(() => {
    navigatingRef.current = true;
    if (resetTimer.current) clearTimeout(resetTimer.current);
    resetTimer.current = setTimeout(() => { navigatingRef.current = false; }, 500);
  }, []);

  // eslint-disable-next-line react-hooks/immutability -- intentional: router monkey-patching restored in cleanup
  useEffect(() => {
    if (!active) return;

    const confirmLeave = () => {
      return window.confirm("작성 중인 내용이 있습니다. 정말 나가시겠습니까?");
    };

    const beforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", beforeUnload);

    const origBack = window.history.back.bind(window.history);
    const origGo = window.history.go.bind(window.history);
    const origPushState = history.pushState.bind(history);

    window.history.back = () => {
      if (navigatingRef.current || !activeRef.current || confirmLeave()) {
        markNavigating();
        origGo(-2);
      }
    };
    window.history.go = (delta?: number) => {
      if (navigatingRef.current || !(delta !== undefined && delta < 0) || confirmLeave()) {
        markNavigating();
        origGo(delta);
      }
    };

    const origRouterPush = router.push.bind(router);
    const origRouterReplace = router.replace.bind(router);

    const routerPatch = router as unknown as {
      push: (...args: Parameters<typeof origRouterPush>) => void;
      replace: (...args: Parameters<typeof origRouterReplace>) => void;
      back: () => void;
    };

    // eslint-disable-next-line react-hooks/immutability -- intentional: router monkey-patching restored in cleanup
    routerPatch.push = (...args: Parameters<typeof origRouterPush>) => {
      if (navigatingRef.current || !activeRef.current || confirmLeave()) {
        markNavigating();
        return origRouterPush(...args);
      }
    };
    routerPatch.replace = (...args: Parameters<typeof origRouterReplace>) => {
      if (navigatingRef.current || !activeRef.current || confirmLeave()) {
        markNavigating();
        return origRouterReplace(...args);
      }
    };
    routerPatch.back = () => {
      if (navigatingRef.current || !activeRef.current || confirmLeave()) {
        markNavigating();
        origGo(-2);
      }
    };

    const onPopState = () => {
      if (navigatingRef.current) return;
      origPushState(null, "", location.href);
      if (!activeRef.current || confirmLeave()) {
        markNavigating();
        origGo(-2);
      }
    };
    origPushState(null, "", location.href);
    window.addEventListener("popstate", onPopState);

    const onClick = (e: MouseEvent) => {
      if (navigatingRef.current || !activeRef.current) return;
      const anchor = (e.target as HTMLElement).closest("a[href]");
      if (!anchor) return;
      const href = anchor.getAttribute("href");
      if (!href || href.startsWith("#") || href.startsWith("javascript:")) return;
      if ((anchor as HTMLAnchorElement).target === "_blank") return;
      if (anchor.closest("form")) return;
      e.preventDefault();
      if (confirmLeave()) {
        markNavigating();
        origRouterPush(href);
      }
    };
    document.addEventListener("click", onClick, true);

    return () => {
      if (resetTimer.current) clearTimeout(resetTimer.current);
      window.removeEventListener("beforeunload", beforeUnload);
      window.removeEventListener("popstate", onPopState);
      document.removeEventListener("click", onClick, true);
      window.history.back = origBack;
      window.history.go = origGo;
      history.pushState = origPushState;
      router.push = origRouterPush;
      router.replace = origRouterReplace;
      router.back = () => { origBack(); };
    };
  }, [active, router, markNavigating]);

  return { suppress };
}
