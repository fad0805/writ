"use client";
import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Placeholder from "@tiptap/extension-placeholder";
import { useEffect } from "react";

export default function EpisodeEditor({ value, onChange }: { value: string; onChange: (html: string) => void }) {
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: { levels: [2, 3] },
      }),
      Placeholder.configure({ placeholder: "소설 내용을 입력하세요..." }),
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

  return (
    <div className="episode-editor">
      <div className="episode-editor-toolbar">
        <button type="button" onClick={() => editor?.chain().focus().toggleBold().run()} data-active={editor?.isActive("bold")}>B</button>
        <button type="button" onClick={() => editor?.chain().focus().toggleItalic().run()} data-active={editor?.isActive("italic")}><em>I</em></button>
        <button type="button" onClick={() => editor?.chain().focus().toggleHeading({ level: 2 }).run()} data-active={editor?.isActive("heading", { level: 2 })}>H2</button>
        <button type="button" onClick={() => editor?.chain().focus().toggleHeading({ level: 3 }).run()} data-active={editor?.isActive("heading", { level: 3 })}>H3</button>
        <button type="button" onClick={() => editor?.chain().focus().toggleBlockquote().run()} data-active={editor?.isActive("blockquote")}>⏎</button>
        <button type="button" onClick={() => editor?.chain().focus().toggleBulletList().run()} data-active={editor?.isActive("bulletList")}>•</button>
        <button type="button" onClick={() => editor?.chain().focus().toggleOrderedList().run()} data-active={editor?.isActive("orderedList")}>1.</button>
        <button type="button" onClick={() => editor?.chain().focus().setHorizontalRule().run()}>—</button>
      </div>
      <EditorContent editor={editor} className="episode-editor-content" />
    </div>
  );
}
