'use client'

import { COLOR_PICKER_PALLETE } from "@/const/extensions";
import { Editor } from "@tiptap/core";
import { useEffect, useState } from "react";

export default function ColorPicker({ref, onClose, editor}: {ref: React.RefObject<HTMLDivElement | null>; onClose: (state: boolean) => void; editor: Editor}) {
  const [recentColors, setRecentColors] = useState<string[] | null>(() => {
    try {
      const savedColor = localStorage.getItem('writ:recent-colors');
      return savedColor ? JSON.parse(savedColor) : [];
    } catch {
      return [];
    }
  })

  const saveRecentColor = (color: string) => { 
    setRecentColors((prev) => {
      if (!prev) return [];
      const list = prev.filter((c) => c !== color);
      list.unshift(color);
      if (list.length > 5) list.length = 5;
      localStorage.setItem("writ:recent-colors", JSON.stringify(list));
      return list;
    })
  }

  const applyColor = (color: string) => {
    editor.chain().focus().setColor(color).run();
    saveRecentColor(color);
    onClose(false);
  };

  useEffect(() => {
    const clickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current?.contains(e.target as Node)) {
        onClose(false);
      }
    }
    document.addEventListener('pointerdown', clickOutside);

    return () => {
      document.removeEventListener('pointerdown', clickOutside);
    }
  }, [onClose, ref])

  return (
      <div className="episode-editor-colorpicker" ref={ref}>
        {recentColors && recentColors.length > 0 && (
          <>
            {recentColors.map((c) => (
              <button key={`r-${c}`} type="button" title={`${c} (최근)`} style={{ width: 20, height: 20, border: `2px solid var(--accent)`, borderRadius: 3, cursor: "pointer", background: c, display: "inline-block", margin: 1 }} onClick={() => applyColor(c)} />
            ))}
            <div style={{ gridColumn: "1 / -1", height: 1, background: "var(--border)", margin: "3px 0" }} />
          </>
        )}
        {COLOR_PICKER_PALLETE.map((c) => (
          <button key={c} type="button" title={c} style={{ width: 20, height: 20, border: "1px solid var(--border)", borderRadius: 3, cursor: "pointer", background: c, display: "inline-block", margin: 1 }} onClick={() => applyColor(c)} />
        ))}
      </div>
  );
}
