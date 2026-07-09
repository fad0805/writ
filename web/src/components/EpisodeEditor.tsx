"use client";
import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Placeholder from "@tiptap/extension-placeholder";
import TextAlign from "@tiptap/extension-text-align";
import Image from "@tiptap/extension-image";
import { useEffect, useRef } from "react";

const SIZES = ["50", "75", "100"];

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
    const style = `width:${w}%`;
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

  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: { levels: [2, 3] },
      }),
      Placeholder.configure({ placeholder: "소설 내용을 입력하세요..." }),
      TextAlign.configure({ types: ["heading", "paragraph"] }),
      AlignableImage,
    ],
    content: value,
    onUpdate: ({ editor }) => {
      onChange(editor.getHTML());
    },
  });

  useEffect(() => {
    if (editor && value !== editor.getHTML()) {
      editor.commands.setContent(value);
    }
  }, [value, editor]);

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

  const setImgAttr = (key: string, val: string) => {
    if (!editor) return;
    const { from, to } = editor.state.selection;
    editor.state.doc.nodesBetween(from, to, (node, pos) => {
      if (node.type.name === "image") {
        editor.chain().focus().setNodeSelection(pos).updateAttributes("image", { [key]: val }).run();
        return false;
      }
    });
  };

  const align = (dir: string) => {
    if (!editor) return;
    if (editor.isActive("image")) {
      setImgAttr("data-align", dir);
      if (dir === "center") setImgAttr("data-wrap", "true");
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
    setImgAttr("data-width", next);
  };

  const toggleWrap = () => {
    const cur = imgAttr("data-wrap");
    setImgAttr("data-wrap", cur === "false" ? "true" : "false");
  };

  const isImageSelected = editor?.isActive("image") ?? false;
  const imgAlign = imgAttr("data-align");
  const imgWrap = imgAttr("data-wrap");

  return (
    <div className="episode-editor">
      <div className="episode-editor-toolbar">
        <button type="button" onClick={() => editor?.chain().focus().toggleHeading({ level: 2 }).run()} data-active={editor?.isActive("heading", { level: 2 })}>H2</button>
        <button type="button" onClick={() => editor?.chain().focus().toggleHeading({ level: 3 }).run()} data-active={editor?.isActive("heading", { level: 3 })}>H3</button>
        <button type="button" onClick={() => editor?.chain().focus().toggleBlockquote().run()} data-active={editor?.isActive("blockquote")}>⏎</button>
        <button type="button" onClick={() => editor?.chain().focus().toggleBulletList().run()} data-active={editor?.isActive("bulletList")}>•</button>
        <button type="button" onClick={() => editor?.chain().focus().toggleOrderedList().run()} data-active={editor?.isActive("orderedList")}>1.</button>
        <button type="button" onClick={() => editor?.chain().focus().setHorizontalRule().run()}>—</button>
        <span className="toolbar-sep" />
        <button type="button" onClick={() => align("left")} data-active={isAlign("left")}>←</button>
        <button type="button" onClick={() => align("center")} data-active={isAlign("center")}>↔</button>
        <button type="button" onClick={() => align("right")} data-active={isAlign("right")}>→</button>
        <span className="toolbar-sep" />
        <button type="button" onClick={() => fileRef.current?.click()} title="이미지 첨부">🖼</button>
        <button type="button" onClick={cycleSize} title="이미지 크기">{isImageSelected ? `${imgAttr("data-width") || "75"}%` : "□"}</button>
        {isImageSelected && imgAlign && imgAlign !== "center" && (
          <button type="button" onClick={toggleWrap} data-active={imgWrap === "true"} title="텍스트 줄바꿈">{imgWrap === "true" ? "↩" : "↪"}</button>
        )}
      </div>
      <input ref={fileRef} type="file" accept="image/*" hidden onChange={handleImageUpload} />
      <EditorContent editor={editor} className="episode-editor-content" />
      <style>{`
        .episode-editor-content img[data-align="left"][data-wrap="true"] { float: left; margin: 0 16px 8px 0; }
        .episode-editor-content img[data-align="right"][data-wrap="true"] { float: right; margin: 0 0 8px 16px; }
        .episode-editor-content img[data-align="left"][data-wrap="false"] { display: block; margin: 8px 0; }
        .episode-editor-content img[data-align="right"][data-wrap="false"] { display: block; margin: 8px 0 8px auto; }
        .episode-editor-content img[data-align="center"] { display: block; margin: 8px auto; }
        .toolbar-sep { display: inline-block; width: 1px; height: 20px; background: var(--border); margin: 0 4px; vertical-align: middle; }
      `}</style>
    </div>
  );
}
