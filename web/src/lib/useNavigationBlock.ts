"use client";
import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";

export function useNavigationBlock(active: boolean) {
  const router = useRouter();
  const activeRef = useRef(active);
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
    const origPushState = history.pushState.bind(history);
    const origReplaceState = history.replaceState.bind(history);

    window.history.back = () => {
      if (!activeRef.current || confirmLeave()) origBack();
    };
    window.history.go = (delta?: number) => {
      if (!activeRef.current || (delta !== undefined && delta < 0)) {
        if (!activeRef.current || confirmLeave()) origGo(delta);
      } else {
        origGo(delta);
      }
    };

    const origRouterPush = router.push.bind(router);
    const origRouterReplace = router.replace.bind(router);
    const origRouterBack = router.back.bind(router);

    (router as any).push = (...args: Parameters<typeof origRouterPush>) => {
      if (!activeRef.current || confirmLeave()) return origRouterPush(...args);
    };
    (router as any).replace = (...args: Parameters<typeof origRouterReplace>) => {
      if (!activeRef.current || confirmLeave()) return origRouterReplace(...args);
    };
    (router as any).back = () => {
      if (!activeRef.current || confirmLeave()) return origRouterBack();
    };

    const onClick = (e: MouseEvent) => {
      if (!activeRef.current) return;
      const anchor = (e.target as HTMLElement).closest("a[href]");
      if (!anchor) return;
      const href = anchor.getAttribute("href");
      if (!href || href.startsWith("#") || href.startsWith("javascript:")) return;
      if ((anchor as HTMLAnchorElement).target === "_blank") return;
      if (anchor.closest("form")) return;
      e.preventDefault();
      if (confirmLeave()) origRouterPush(href);
    };
    document.addEventListener("click", onClick, true);

    return () => {
      window.removeEventListener("beforeunload", beforeUnload);
      document.removeEventListener("click", onClick, true);
      window.history.back = origBack;
      window.history.go = origGo;
      window.history.pushState = origPushState;
      window.history.replaceState = origReplaceState;
      router.push = origRouterPush;
      router.replace = origRouterReplace;
      router.back = origRouterBack;
    };
  }, [active, router]);
}
