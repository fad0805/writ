"use client";
import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";

export function useNavigationBlock(active: boolean) {
  const router = useRouter();
  const activeRef = useRef(active);
  const navigatingRef = useRef(false);
  activeRef.current = active;

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

    window.history.back = () => {
      if (navigatingRef.current || !activeRef.current || confirmLeave()) {
        navigatingRef.current = true;
        origBack();
      }
    };
    window.history.go = (delta?: number) => {
      if (navigatingRef.current || !(delta !== undefined && delta < 0) || confirmLeave()) {
        navigatingRef.current = true;
        origGo(delta);
      }
    };

    const origRouterPush = router.push.bind(router);
    const origRouterReplace = router.replace.bind(router);

    (router as any).push = (...args: Parameters<typeof origRouterPush>) => {
      if (navigatingRef.current || !activeRef.current || confirmLeave()) {
        navigatingRef.current = true;
        return origRouterPush(...args);
      }
    };
    (router as any).replace = (...args: Parameters<typeof origRouterReplace>) => {
      if (navigatingRef.current || !activeRef.current || confirmLeave()) {
        navigatingRef.current = true;
        return origRouterReplace(...args);
      }
    };
    (router as any).back = () => {
      if (navigatingRef.current || !activeRef.current || confirmLeave()) {
        navigatingRef.current = true;
        origBack();
      }
    };

    const onPopState = () => {
      if (navigatingRef.current) return;
      if (!activeRef.current || confirmLeave()) {
        navigatingRef.current = true;
        return;
      }
      history.pushState(null, "", location.href);
    };
    history.pushState(null, "", location.href);
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
        navigatingRef.current = true;
        origRouterPush(href);
      }
    };
    document.addEventListener("click", onClick, true);

    return () => {
      window.removeEventListener("beforeunload", beforeUnload);
      window.removeEventListener("popstate", onPopState);
      document.removeEventListener("click", onClick, true);
      window.history.back = origBack;
      window.history.go = origGo;
      router.push = origRouterPush;
      router.replace = origRouterReplace;
      router.back = () => { origBack(); };
    };
  }, [active, router]);
}
