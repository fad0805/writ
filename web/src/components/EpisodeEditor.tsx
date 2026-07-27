"use client";

import { useEditorActions, useEditorInit } from "@/hooks/useEditorAction";
import { EditorContent } from "@tiptap/react";
import { useRef, useState, useEffect, useCallback, useMemo } from "react";
import ColorPicker from "./ColorPicker";
import { splitIntoPages, joinPages } from "@/lib/pages";

export default function EpisodeEditor({ value, onChange }: { value: string; onChange: (html: string) => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [showColorPicker, setShowColorPicker] = useState(false);
  const colorPickerRef = useRef<HTMLDivElement>(null);

  const pages = useMemo(() => splitIntoPages(value || ""), [value]);
  const [currentPage, setCurrentPage] = useState(0);
  const [pageContent, setPageContent] = useState(pages[currentPage] || "");

  useEffect(() => {
    const newPages = splitIntoPages(value || "");
    const restoredPage = Math.min(currentPage, newPages.length - 1);
    setCurrentPage(restoredPage);
    setPageContent(newPages[restoredPage] || "");
  }, [value]);

  const emitChange = useCallback((newPageContent: string, pageIndex: number) => {
    const allPages = splitIntoPages(value || "");
    allPages[pageIndex] = newPageContent;
    onChange(joinPages(allPages));
  }, [value, onChange]);

  const handlePageChange = useCallback((newHtml: string) => {
    setPageContent(newHtml);
    emitChange(newHtml, currentPage);
  }, [currentPage, emitChange]);

  const editor = useEditorInit({ value: pageContent, onChange: handlePageChange });
  const editorFn = useEditorActions(editor);

  useEffect(() => {
    if (!editor) return;
    const target = pages[currentPage] || "";
    if (editor.getHTML() !== target) {
      editor.commands.setContent(target, { emitUpdate: false });
    }
  }, [currentPage, pages]);

  const goToPage = (idx: number) => {
    if (idx < 0 || idx >= pages.length) return;
    setCurrentPage(idx);
    setPageContent(pages[idx] || "");
  };

  const startPage = Math.max(0, currentPage - 2);
  const endPage = Math.min(pages.length, startPage + 5);
  const visiblePages = [];
  for (let i = startPage; i < endPage; i++) visiblePages.push(i);

  return (
    <div className="episode-editor">
      <div className="episode-editor-toolbar">
        <div className="episode-editor-toolbar-section">
          <button type="button" onClick={() => editor?.chain().focus().toggleBold().run()} data-active={editor?.isActive("bold")}><b>B</b></button>
          <button type="button" onClick={() => editor?.chain().focus().toggleItalic().run()} data-active={editor?.isActive("italic")}><i>I</i></button>
          <button type="button" onClick={() => editor?.chain().focus().toggleUnderline().run()} data-active={editor?.isActive("underline")}><u>U</u></button>
          <button type="button" onClick={() => editor?.chain().focus().toggleStrike().run()} data-active={editor?.isActive("strike")}><s>S</s></button>
        </div>
        <div className="episode-editor-toolbar-section">
          <div style={{ position: "relative", display: "inline-block" }}>
            <button type="button" onClick={() => setShowColorPicker(!showColorPicker)} style={{ color: editor?.getAttributes("textStyle").color || "inherit", fontWeight: 600 }}>A</button>
            {showColorPicker && (
              <ColorPicker
                onClose={setShowColorPicker}
                ref={colorPickerRef}
                editor={editor}/>
            )}
          </div>
        </div>
        <div className="episode-editor-toolbar-section">
          <button type="button" onClick={() => editor?.chain().focus().toggleHeading({ level: 2 }).run()} data-active={editor?.isActive("heading", { level: 2 })}>H2</button>
          <button type="button" onClick={() => editor?.chain().focus().toggleHeading({ level: 3 }).run()} data-active={editor?.isActive("heading", { level: 3 })}>H3</button>
          <button type="button" onClick={() => editor?.chain().focus().toggleBlockquote().run()} data-active={editor?.isActive("blockquote")}>⏎</button>
          <button type="button" onClick={() => editor?.chain().focus().toggleBulletList().run()} data-active={editor?.isActive("bulletList")}>•</button>
          <button type="button" onClick={() => editor?.chain().focus().toggleOrderedList().run()} data-active={editor?.isActive("orderedList")}>1.</button>
          <button type="button" onClick={() => editor?.chain().focus().setHorizontalRule().run()}>—</button>
          <button type="button" onClick={() => editor?.chain().focus().toggleCodeBlock().run()} data-active={editor?.isActive("codeBlock")} title="코드 블록"><span style={{ fontFamily: "monospace", fontSize: 13, fontWeight: 700 }}>{'</>'}</span></button>
          <button type="button" onClick={() => editor?.chain().focus().toggleCode().run()} data-active={editor?.isActive("code")} title="인라인 코드"><code style={{ fontSize: 12 }}>{'<>'}</code></button>
        </div>
        <div className="episode-editor-toolbar-section">
          <button type="button" onClick={() => editorFn?.align("left")} data-active={editorFn?.isAlign("left")}>←</button>
          <button type="button" onClick={() => editorFn?.align("center")} data-active={editorFn?.isAlign("center")}>↔</button>
          <button type="button" onClick={() => editorFn?.align("right")} data-active={editorFn?.isAlign("right")}>→</button>
        </div>
        <div className="episode-editor-toolbar-section">
          <button type="button" onClick={() => fileRef.current?.click()} title="이미지 첨부">🖼</button>
          <button type="button" onClick={editorFn?.cycleSize} title="이미지 크기">{editorFn?.isImageSelected ? `${editorFn?.imgAttr("data-width") || "75"}%` : "□"}</button>
          {editorFn?.isImageSelected && editorFn?.imgAlign && editorFn?.imgAlign !== "center" && (
            <button type="button" onClick={editorFn?.toggleWrap} data-active={editorFn?.imgWrap === "true"} title="텍스트 줄바꿈">{editorFn?.imgWrap === "true" ? "↩" : "↪"}</button>
          )}
        </div>
      </div>
      <input ref={fileRef} type="file" accept="image/*" hidden onChange={editorFn?.handleImgUpload} />
      <EditorContent editor={editor} className="episode-editor-content" />
      {pages.length > 1 && (
        <div className="episode-page-nav">
          <button type="button" className="episode-page-arrow" disabled={currentPage === 0} onClick={() => goToPage(currentPage - 1)}>‹</button>
          {visiblePages[0] > 0 && <span className="episode-page-ellipsis">…</span>}
          {visiblePages.map(i => (
            <button key={i} type="button" className={`episode-page-num${i === currentPage ? " active" : ""}`} onClick={() => goToPage(i)}>{i + 1}</button>
          ))}
          {visiblePages[visiblePages.length - 1] < pages.length - 1 && <span className="episode-page-ellipsis">…</span>}
          <button type="button" className="episode-page-arrow" disabled={currentPage === pages.length - 1} onClick={() => goToPage(currentPage + 1)}>›</button>
          <span className="episode-page-total">{currentPage + 1} / {pages.length}</span>
        </div>
      )}
    </div>
  );
}
