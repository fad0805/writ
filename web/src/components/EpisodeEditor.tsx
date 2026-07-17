"use client";
import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Placeholder from "@tiptap/extension-placeholder";
import TextAlign from "@tiptap/extension-text-align";
import Image from "@tiptap/extension-image";
import Underline from "@tiptap/extension-underline";
import Strike from "@tiptap/extension-strike";
import { TextStyle } from "@tiptap/extension-text-style";
import { Color } from "@tiptap/extension-color";
import { useEffect, useRef, useState, useMemo } from "react";

const SIZES = ["50", "75", "100"];

const CustomStrike = Strike.extend({
  addInputRules() {
    return [];
  },
});

const AlignableImage = Image.extend({
  addAttributes() {
    return {
      src: { default: null },
      alt: { default: null },
      "data-align": { default: "center" },
      "data-width": { default: "75" },
      "data-wrap": { default: "true" },
    };
  },
  renderHTML({ node, HTMLAttributes }) {
    const w = node.attrs["data-width"] as string;
    const align = node.attrs["data-align"] as string;
    const wrap = node.attrs["data-wrap"] as string;
    let style = `width:${w}%`;
    if (align === "left" && wrap === "true") style += "; float: left; margin: 0 16px 8px 0";
    else if (align === "right" && wrap === "true") style += "; float: right; margin: 0 0 8px 16px";
    else if (align === "left" && wrap === "false") style += "; display: block; margin: 8px 0";
    else if (align === "right" && wrap === "false") style += "; display: block; margin: 8px 0 8px auto";
    else if (align === "center") style += "; display: block; margin: 8px auto";
    return ["img", { ...HTMLAttributes, style }];
  },
  parseHTML() {
    return [{
      tag: "img",
      getAttrs: (el) => ({
        "data-align": (el as HTMLElement).getAttribute("data-align") || "center",
        "data-width": (el as HTMLElement).getAttribute("data-width") || "75",
        "data-wrap": (el as HTMLElement).getAttribute("data-wrap") || "true",
      }),
    }];
  },
});

export default function EpisodeEditor({ value, onChange }: { value: string; onChange: (html: string) => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [showColorPicker, setShowColorPicker] = useState(false);
  const colorPickerRef = useRef<HTMLDivElement>(null);
  const internalUpdate = useRef(false);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const initialSet = useRef(false);
  const recentColorsRef = useRef<string[]>([]);

  useEffect(() => {
    try {
      const saved = localStorage.getItem("writ:recent-colors");
      if (saved) recentColorsRef.current = JSON.parse(saved);
    } catch {}
  }, []);

  const extensions = useMemo(() => [
    StarterKit.configure({
      heading: { levels: [2, 3] },
      strike: false,
    }),
    CustomStrike,
    Underline,
    TextStyle,
    Color,
    Placeholder.configure({ placeholder: "소설 내용을 입력하세요..." }),
    TextAlign.configure({ types: ["heading", "paragraph"] }),
    AlignableImage,
  ], []);

  const editor = useEditor({
    extensions,
    onUpdate: ({ editor }) => {
      internalUpdate.current = true;
      onChangeRef.current(editor.getHTML());
    },
  });

  useEffect(() => {
    if (!editor) return;
    if (!initialSet.current) {
      if (value) {
        editor.commands.setContent(value, { emitUpdate: false } as any);
      }
      initialSet.current = true;
    }
  }, [editor, value]);

  useEffect(() => {
    if (!showColorPicker) return;
    const close = (e: MouseEvent) => {
      if (colorPickerRef.current && !colorPickerRef.current.contains(e.target as Node)) setShowColorPicker(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [showColorPicker]);

  const handleImageUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !editor) return;
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await fetch("/api/media/upload", { method: "POST", credentials: "include", body: formData });
      if (res.ok) {
        const d = await res.json();
        editor.chain().focus().setImage({ src: d.url }).run();
      }
    } catch {}
    e.target.value = "";
  };

  const imgAttr = (key: string) => {
    if (!editor) return null;
    const { from, to } = editor.state.selection;
    let val: string | null = null;
    editor.state.doc.nodesBetween(from, to, (node) => {
      if (node.type.name === "image") val = node.attrs[key] as string;
    });
    return val;
  };

  const align = (dir: string) => {
    if (!editor) return;
    if (editor.isActive("image")) {
      editor.chain().focus().updateAttributes("image", { "data-align": dir }).run();
      if (dir === "center") editor.chain().focus().updateAttributes("image", { "data-wrap": "true" }).run();
    } else {
      editor.chain().focus().setTextAlign(dir).run();
    }
  };

  const isAlign = (dir: string) => {
    if (!editor) return false;
    if (editor.isActive("image")) return imgAttr("data-align") === dir;
    return editor.isActive({ textAlign: dir });
  };

  const cycleSize = () => {
    const cur = imgAttr("data-width") || "75";
    const idx = SIZES.indexOf(cur);
    const next = SIZES[(idx + 1) % SIZES.length];
    editor?.chain().focus().updateAttributes("image", { "data-width": next }).run();
  };

  const toggleWrap = () => {
    const cur = imgAttr("data-wrap");
    editor?.chain().focus().updateAttributes("image", { "data-wrap": cur === "false" ? "true" : "false" }).run();
  };

  const isImageSelected = editor?.isActive("image") ?? false;
  const imgAlign = imgAttr("data-align");
  const imgWrap = imgAttr("data-wrap");

  const saveRecentColor = (color: string) => {
    const list = recentColorsRef.current.filter((c) => c !== color);
    list.unshift(color);
    if (list.length > 5) list.length = 5;
    recentColorsRef.current = list;
    try { localStorage.setItem("writ:recent-colors", JSON.stringify(list)); } catch {}
  };

  const applyColor = (color: string) => {
    editor?.chain().focus().setColor(color).run();
    saveRecentColor(color);
    setShowColorPicker(false);
  };

  return (
    <div className="episode-editor">
      <div className="episode-editor-toolbar">
        <button type="button" onClick={() => editor?.chain().focus().toggleBold().run()} data-active={editor?.isActive("bold")}><b>B</b></button>
        <button type="button" onClick={() => editor?.chain().focus().toggleItalic().run()} data-active={editor?.isActive("italic")}><i>I</i></button>
        <button type="button" onClick={() => editor?.chain().focus().toggleUnderline().run()} data-active={editor?.isActive("underline")}><u>U</u></button>
        <button type="button" onClick={() => editor?.chain().focus().toggleStrike().run()} data-active={editor?.isActive("strike")}><s>S</s></button>
        <span className="toolbar-sep">:</span>
        <div style={{ position: "relative", display: "inline-block" }}>
          <button type="button" onClick={() => setShowColorPicker(!showColorPicker)} style={{ color: editor?.getAttributes("textStyle").color || "inherit", fontWeight: 600 }}>A</button>
          {showColorPicker && (
            <div ref={colorPickerRef} className="episode-editor-colorpicker" onClick={(e) => e.stopPropagation()}>
              {recentColorsRef.current.length > 0 && (
                <>
                  {recentColorsRef.current.map((c) => (
                    <button key={`r-${c}`} type="button" title={`${c} (최근)`} style={{ width: 20, height: 20, border: `2px solid var(--accent)`, borderRadius: 3, cursor: "pointer", background: c, display: "inline-block", margin: 1 }} onClick={() => applyColor(c)} />
                  ))}
                  <div style={{ gridColumn: "1 / -1", height: 1, background: "var(--border)", margin: "3px 0" }} />
                </>
              )}
              {["#000000","#434343","#666666","#999999","#b7b7b7","#cccccc","#d9d9d9","#efefef","#f3f3f3","#ffffff",
                "#980000","#ff0000","#ff9900","#ffff00","#00ff00","#00ffff","#4a86e8","#0000ff","#9900ff","#ff00ff",
                "#e6b8af","#f4cccc","#fce5cd","#fff2cc","#d9ead3","#d0e0e3","#c9daf8","#cfe2f3","#d9d2e9","#ead1dc",
                "#dd7e6b","#ea9999","#f9cb9c","#ffe599","#b6d7a8","#a2c4c9","#a4c2f4","#9fc5e8","#b4a7d6","#d5a6bd",
                "#cc4125","#e06666","#f6b26b","#ffd966","#93c47d","#76a5af","#6d9eeb","#6fa8dc","#8e7cc3","#c27ba0",
                "#a61c00","#cc0000","#e69138","#f1c232","#6aa84f","#45818e","#3c78d8","#3d85c6","#674ea7","#a64d79",
                "#85200c","#990000","#b45f06","#bf9000","#38761d","#134f5c","#1155cc","#0b5394","#351c75","#741b47",
                "#5b0f00","#660000","#783f04","#7f6000","#274e13","#0c343d","#1c4587","#073763","#20124d","#4c1130"
              ].map((c) => (
                <button key={c} type="button" title={c} style={{ width: 20, height: 20, border: "1px solid var(--border)", borderRadius: 3, cursor: "pointer", background: c, display: "inline-block", margin: 1 }} onClick={() => applyColor(c)} />
              ))}
            </div>
          )}
        </div>
        <span className="toolbar-sep">:</span>
        <button type="button" onClick={() => editor?.chain().focus().toggleHeading({ level: 2 }).run()} data-active={editor?.isActive("heading", { level: 2 })}>H2</button>
        <button type="button" onClick={() => editor?.chain().focus().toggleHeading({ level: 3 }).run()} data-active={editor?.isActive("heading", { level: 3 })}>H3</button>
        <button type="button" onClick={() => editor?.chain().focus().toggleBlockquote().run()} data-active={editor?.isActive("blockquote")}>⏎</button>
        <button type="button" onClick={() => editor?.chain().focus().toggleBulletList().run()} data-active={editor?.isActive("bulletList")}>•</button>
        <button type="button" onClick={() => editor?.chain().focus().toggleOrderedList().run()} data-active={editor?.isActive("orderedList")}>1.</button>
        <button type="button" onClick={() => editor?.chain().focus().setHorizontalRule().run()}>—</button>
        <button type="button" onClick={() => editor?.chain().focus().toggleCodeBlock().run()} data-active={editor?.isActive("codeBlock")} title="코드 블록"><span style={{ fontFamily: "monospace", fontSize: 13, fontWeight: 700 }}>{ }</span></button>
        <span className="toolbar-sep">:</span>
        <button type="button" onClick={() => align("left")} data-active={isAlign("left")}>←</button>
        <button type="button" onClick={() => align("center")} data-active={isAlign("center")}>↔</button>
        <button type="button" onClick={() => align("right")} data-active={isAlign("right")}>→</button>
        <span className="toolbar-sep">:</span>
        <button type="button" onClick={() => fileRef.current?.click()} title="이미지 첨부">🖼</button>
        <button type="button" onClick={cycleSize} title="이미지 크기">{isImageSelected ? `${imgAttr("data-width") || "75"}%` : "□"}</button>
        {isImageSelected && imgAlign && imgAlign !== "center" && (
          <button type="button" onClick={toggleWrap} data-active={imgWrap === "true"} title="텍스트 줄바꿈">{imgWrap === "true" ? "↩" : "↪"}</button>
        )}
      </div>
      <input ref={fileRef} type="file" accept="image/*" hidden onChange={handleImageUpload} />
      <EditorContent editor={editor} className="episode-editor-content" />
      <style>{`
        .episode-editor-content img.ProseMirror-selectednode { outline: 3px solid var(--accent); outline-offset: 2px; border-radius: 4px; }
        .toolbar-sep { color: var(--text-dim); margin: 0 2px; font-size: 0.85em; vertical-align: middle; }
        .episode-editor-colorpicker { position: absolute; top: 100%; left: 0; z-index: 50; display: grid; grid-template-columns: repeat(10, 20px); gap: 1px; padding: 6px; background: var(--bg-primary); border: 1px solid var(--border); border-radius: 8px; box-shadow: 0 4px 16px rgba(0,0,0,0.15); margin-top: 4px; }
      `}</style>
    </div>
  );
}
