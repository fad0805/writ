import Image from "@tiptap/extension-image";
import Placeholder from "@tiptap/extension-placeholder";
import Strike from "@tiptap/extension-strike";
import TextAlign from "@tiptap/extension-text-align";
import { Color, TextStyle } from "@tiptap/extension-text-style";
import Underline from "@tiptap/extension-underline";
import StarterKit from "@tiptap/starter-kit";

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

export const EDITOR_EXTENSIONS = [
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
]
