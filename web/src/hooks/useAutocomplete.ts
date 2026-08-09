import { useCallback, useEffect, useRef, useState } from "react";

export interface SeriesResult {
  id: number;
  title: string;
  cover_image: string;
}

interface InlineAutocompleteOptions<T> {
  trigger: string;
  prevCharRegex: RegExp;
  wordEndRegex: RegExp;
  search: (query: string) => Promise<T[]>;
  content: string;
  setContent: React.Dispatch<React.SetStateAction<string>>;
  taRef: React.RefObject<HTMLTextAreaElement | null>;
}

export function useInlineAutocomplete<T>({
  trigger,
  prevCharRegex,
  wordEndRegex,
  search,
  content,
  setContent,
  taRef,
}: InlineAutocompleteOptions<T>) {
  const [start, setStart] = useState(-1);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<T[]>([]);
  const [idx, setIdx] = useState(0);
  const [pos, setPos] = useState({ top: 0, left: 0 });

  const searchRef = useRef(search);
  useEffect(() => {
    searchRef.current = search;
  });

  const queryRef = useRef("");
  const hadQueryRef = useRef(false);

  useEffect(() => {
    if (queryRef.current !== query) {
      queryRef.current = query;
      if (hadQueryRef.current !== !!query) {
        hadQueryRef.current = !!query;
        setResults([]);
      }
      if (query) {
        const t = setTimeout(async () => {
          try {
            const res = await searchRef.current(query);
            setResults(res);
            setIdx(0);
          } catch {
            setResults([]);
          }
        }, 100);
        return () => clearTimeout(t);
      }
    }
  }, [query]);

  const detect = useCallback(
    (val: string, cursor: number) => {
      const before = val.slice(0, cursor);
      const trigIdx = before.lastIndexOf(trigger);
      if (trigIdx === -1 || (trigIdx > 0 && !prevCharRegex.test(val[trigIdx - 1]))) {
        setStart(-1);
        setQuery("");
        setResults([]);
        return;
      }
      const partial = before.slice(trigIdx + 1);
      if (partial.length === 0 || new RegExp(`[\\s${trigger}]`).test(partial)) {
        setStart(-1);
        setQuery("");
        setResults([]);
        return;
      }
      setStart(trigIdx);
      setQuery(partial);
      const ta = taRef.current;
      if (ta) {
        const rect = ta.getBoundingClientRect();
        const lineHeight = parseInt(getComputedStyle(ta).lineHeight) || 20;
        const textBefore = val.slice(0, cursor);
        const lines = textBefore.split("\n");
        const top = rect.top + lines.length * lineHeight + 4;
        const lastLine = lines[lines.length - 1] || "";
        const left = rect.left + lastLine.length * 8 + 10;
        setPos({ top, left });
      }
    },
    [trigger, prevCharRegex, taRef]
  );

  const reset = useCallback(() => {
    setStart(-1);
    setQuery("");
    setResults([]);
  }, []);

  const insert = useCallback(
    (value: string, suffix = " ") => {
      if (start === -1) return;
      const afterTrigger = content.slice(start + 1);
      const wordEndMatch = afterTrigger.search(wordEndRegex);
      const wordEnd = start + 1 + (wordEndMatch >= 0 ? wordEndMatch : afterTrigger.length);
      const before = content.slice(0, start);
      const after = content.slice(wordEnd);
      const inserted = `${before}${trigger}${value}${suffix}${after}`;
      setContent(inserted);
      reset();
      requestAnimationFrame(() => {
        const ta = taRef.current;
        if (ta) {
          const pos = before.length + trigger.length + value.length + suffix.length;
          ta.setSelectionRange(pos, pos);
          ta.focus();
        }
      });
    },
    [start, content, trigger, wordEndRegex, setContent, reset, taRef]
  );

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent, onSelect: (item: T) => void): boolean => {
      if (results.length === 0) return false;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setIdx((i) => Math.min(i + 1, results.length - 1));
        return true;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setIdx((i) => Math.max(i - 1, 0));
        return true;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        if (results[idx]) onSelect(results[idx]);
        return true;
      }
      if (e.key === "Escape") {
        setResults([]);
        return true;
      }
      return false;
    },
    [results, idx]
  );

  return { start, query, results, idx, pos, setIdx, setResults, detect, reset, insert, onKeyDown };
}

export function useSeriesSearch({
  content,
  setContent,
  taRef,
}: {
  content: string;
  setContent: React.Dispatch<React.SetStateAction<string>>;
  taRef: React.RefObject<HTMLTextAreaElement | null>;
}) {
  const [show, setShow] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SeriesResult[]>([]);
  const [idx, setIdx] = useState(0);
  const [pos, setPos] = useState({ top: 0, left: 0 });
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!show) return;
    const t = setTimeout(async () => {
      try {
        const res = await fetch(`/api/search/series?q=${encodeURIComponent(query)}`, { credentials: "include" });
        if (res.ok) {
          const d = await res.json();
          setResults(d.series?.map((s: { id: number; title: string; cover_image: string }) => ({ id: s.id, title: s.title, cover_image: s.cover_image })) || []);
          setIdx(0);
        } else {
          setResults([]);
        }
      } catch {
        setResults([]);
      }
    }, 100);
    return () => clearTimeout(t);
  }, [query, show]);

  const removeCommand = useCallback(() => {
    const cur = taRef.current?.value || content;
    const slashIdx = cur.lastIndexOf("/");
    if (slashIdx >= 0 && (cur.slice(slashIdx + 1).toLowerCase().startsWith("series") || cur.slice(slashIdx + 1).toLowerCase().startsWith("시리즈"))) {
      const after = cur.slice(slashIdx);
      const wordEndMatch = after.search(/[\s]|$/);
      const wordEnd = slashIdx + (wordEndMatch >= 0 ? wordEndMatch : after.length);
      setContent((cur.slice(0, slashIdx - 1) + cur.slice(wordEnd)).replace(/^\s+/, ""));
    }
    setShow(false);
    setResults([]);
  }, [content, taRef, setContent]);

  useEffect(() => {
    if (!show) return;
    const keyHandler = (e: KeyboardEvent) => {
      if (e.key === "Escape") removeCommand();
    };
    document.addEventListener("keydown", keyHandler);
    const clickHandler = (e: MouseEvent) => {
      const popup = document.querySelector(".emoji-autocomplete");
      if (popup && !popup.contains(e.target as Node)) removeCommand();
    };
    setTimeout(() => document.addEventListener("click", clickHandler), 0);
    return () => {
      document.removeEventListener("keydown", keyHandler);
      document.removeEventListener("click", clickHandler);
    };
  }, [show, removeCommand]);

  const detect = useCallback(
    (val: string, cursor: number) => {
      const before = val.slice(0, cursor);
      const slashIdx = before.lastIndexOf("/");
      if (slashIdx === -1 || (slashIdx > 0 && !/\s/.test(val[slashIdx - 1]))) {
        setShow(false);
        setResults([]);
        return;
      }
      const raw = before.slice(slashIdx + 1);
      const cmd = raw.toLowerCase();
      if (cmd !== "series" && cmd !== "시리즈" && !cmd.startsWith("series ") && !cmd.startsWith("시리즈 ")) {
        setShow(false);
        setResults([]);
        return;
      }
      if (!cmd.includes(" ") && (cmd === "series" || cmd === "시리즈")) {
        setShow(true);
        setQuery("");
        setResults([]);
        const ta = taRef.current;
        if (ta) {
          const rect = ta.getBoundingClientRect();
          const lineHeight = parseInt(getComputedStyle(ta).lineHeight) || 20;
          const textBefore = val.slice(0, cursor);
          const lines = textBefore.split("\n");
          const top = rect.top + lines.length * lineHeight + 4;
          const lastLine = lines[lines.length - 1] || "";
          const left = rect.left + lastLine.length * 8 + 10;
          setPos({ top, left });
        }
        setTimeout(() => inputRef.current?.focus(), 0);
        return;
      }
      setShow(false);
      setResults([]);
    },
    [taRef]
  );

  const insert = useCallback(
    (series: { id: number; title: string }) => {
      const slashIdx = content.lastIndexOf("/");
      const before = slashIdx > 0 ? content.slice(0, slashIdx - 1) : "";
      const fullUrl = `${window.location.origin}/series/${series.id}`;
      const inserted = `${before} ${fullUrl} `;
      setContent(inserted);
      setShow(false);
      setResults([]);
      setQuery("");
      requestAnimationFrame(() => {
        const ta = taRef.current;
        if (ta) {
          ta.setSelectionRange(inserted.length, inserted.length);
          ta.focus();
        }
      });
    },
    [content, taRef, setContent]
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent): boolean => {
      if (!show) return false;
      if (e.key === "Enter") {
        e.preventDefault();
        if (results.length > 0 && results[idx]) insert(results[idx]);
        return true;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        removeCommand();
        return true;
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setIdx((i) => Math.min(i + 1, results.length - 1));
        return true;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setIdx((i) => Math.max(i - 1, 0));
        return true;
      }
      return false;
    },
    [show, results, idx, insert, removeCommand]
  );

  return { show, query, results, idx, pos, setQuery, setIdx, inputRef, detect, insert, handleKeyDown };
}
