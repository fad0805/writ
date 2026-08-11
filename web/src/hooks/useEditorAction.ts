import { SIZES } from "@/const/const";
import { EDITOR_EXTENSIONS } from "@/const/extensions";
import { Editor } from "@tiptap/core";
import { useEditor } from "@tiptap/react";
import { useEffect, useRef } from "react";

export function useEditorInit({value, onChange}: {value: string; onChange: (html: string) => void}) {
  const editor = useEditor({
    extensions: EDITOR_EXTENSIONS,
    content: value || "",
  })

  const onChangeRef = useRef(onChange);

  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

  useEffect(() => {
    if (!editor) return;

    const handler = ({editor}: {editor: Editor}) => {
      onChangeRef.current(editor.getHTML())
    }
    editor.on("update", handler);

    return () => {
      editor.off("update", handler);
    }
  }, [editor])

  useEffect(() => {
    if (!editor || value === undefined) return;
    const incoming = value || "";
    if (editor.getHTML() !== incoming) {
      editor.commands.setContent(incoming, { emitUpdate: false });
    }
  }, [editor, value])

  return editor;
}

export function useEditorActions(editor: Editor | null) {
  if (!editor) return null;

  const imgAttr = (key: string) => {
    const { from, to } = editor.state.selection;
    let val: string | null = null;
    editor.state.doc.nodesBetween(from, to, (node) => {
      if (node.type.name === "image") val = node.attrs[key] as string;
    });
    return val;
  }

  const handleImgUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
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
  }

  const align = (dir: string) => {
    if (editor.isActive("image")) {
      editor.chain().focus().updateAttributes("image", { "data-align": dir }).run();
      if (dir === "center") editor.chain().focus().updateAttributes("image", { "data-wrap": "true" }).run();
    } else {
      editor.chain().focus().setTextAlign(dir).run();
    }
  }

  const isAlign = (dir: string) => {
    if (editor.isActive("image")) return imgAttr("data-align") === dir;
    return editor.isActive({ textAlign: dir });
  }

  const cycleSize = () => {
    const cur = imgAttr("data-width") || "75";
    const idx = SIZES.indexOf(cur);
    const next = SIZES[(idx + 1) % SIZES.length];
    editor.chain().focus().updateAttributes("image", { "data-width": next }).run();
  }

  const toggleWrap = () => {
    const cur = imgAttr("data-wrap");
    editor.chain().focus().updateAttributes("image", { "data-wrap": cur === "false" ? "true" : "false" }).run();
  }

  return {
    imgAlign: imgAttr("data-align"),
    imgWrap: imgAttr("data-wrap"),
    isImageSelected: editor.isActive("image"),
    isAlign, align, cycleSize, toggleWrap, handleImgUpload, imgAttr
  }
}
