"use client";
import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Placeholder from "@tiptap/extension-placeholder";
import Image from "@tiptap/extension-image";
import { useEffect, useRef } from "react";

const AlignableImage = Image.extend({
  addAttributes() {
    return {
      src: { default: null },
      alt: { default: null },
      "data-align": { default: "center" },
    };
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

  const setImageAlign = (align: string) => {
    if (!editor) return;
    const { from, to } = editor.state.selection;
    editor.state.doc.nodesBetween(from, to, (node, pos) => {
      if (node.type.name === "image") {
        editor.chain().focus().setNodeSelection(pos).updateAttributes("image", { "data-align": align }).run();
        return false;
      }
    });
  };

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
        <button type="button" onClick={() => fileRef.current?.click()} title="이미지 첨부">🖼</button>
        <button type="button" onClick={() => setImageAlign("left")} data-active={editor?.isActive("image", { "data-align": "left" })}>←정렬</button>
        <button type="button" onClick={() => setImageAlign("center")} data-active={editor?.isActive("image", { "data-align": "center" })}>가운데</button>
        <button type="button" onClick={() => setImageAlign("right")} data-active={editor?.isActive("image", { "data-align": "right" })}>정렬→</button>
      </div>
      <input ref={fileRef} type="file" accept="image/*" hidden onChange={handleImageUpload} />
      <EditorContent editor={editor} className="episode-editor-content" />
      <style>{`
        .episode-editor-content img[data-align="left"] { float: left; margin: 0 16px 8px 0; max-width: 50%; }
        .episode-editor-content img[data-align="right"] { float: right; margin: 0 0 8px 16px; max-width: 50%; }
        .episode-editor-content img[data-align="center"] { display: block; margin: 8px auto; max-width: 100%; }
        .toolbar-sep { display: inline-block; width: 1px; height: 20px; background: var(--border); margin: 0 4px; vertical-align: middle; }
      `}</style>
    </div>
  );
}
