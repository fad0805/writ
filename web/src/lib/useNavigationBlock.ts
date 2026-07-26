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

    const onPopState = () => {
      if (!activeRef.current || confirmLeave()) return;
      history.pushState(null, "", location.href);
    };
    history.pushState(null, "", location.href);
    window.addEventListener("popstate", onPopState);

    const origPush = router.push.bind(router);
    const origReplace = router.replace.bind(router);
    const origBack = router.back.bind(router);

    (router as any).push = (...args: Parameters<typeof origPush>) => {
      if (!activeRef.current || confirmLeave()) return origPush(...args);
    };
    (router as any).replace = (...args: Parameters<typeof origReplace>) => {
      if (!activeRef.current || confirmLeave()) return origReplace(...args);
    };
    (router as any).back = () => {
      if (!activeRef.current || confirmLeave()) return origBack();
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
      if (confirmLeave()) origPush(href);
    };
    document.addEventListener("click", onClick, true);

    return () => {
      window.removeEventListener("popstate", onPopState);
      window.removeEventListener("beforeunload", beforeUnload);
      document.removeEventListener("click", onClick, true);
      router.push = origPush;
      router.replace = origReplace;
      router.back = origBack;
    };
  }, [active, router]);
}
