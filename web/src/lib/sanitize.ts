import DOMPurify from "dompurify";
import type { Config } from "dompurify";

let hookRegistered = false;

function registerHooks() {
  if (hookRegistered) return;
  hookRegistered = true;
  if (typeof window === "undefined") return;
  DOMPurify.addHook("uponSanitizeAttribute", (node, data) => {
    if (data.attrName === "style") {
      // 레이아웃 공격(전면 오버레이 등)을 막기 위해 style은 이미지에서만 허용한다.
      if (node && node.tagName !== "IMG") {
        data.keepAttr = false;
        return;
      }
      if (
        data.attrValue &&
        /url\s*(\(|\\\()|@import|expression\s*\(|-moz-binding|behavior\s*:/i.test(data.attrValue)
      ) {
        data.keepAttr = false;
      }
    }
  });
  DOMPurify.addHook("afterSanitizeAttributes", (node) => {
    if (node.tagName === "A" && node.getAttribute("target") === "_blank") {
      // tabnabbing 방지: 새 탭으로 열리는 링크에 window.opener 접근을 차단한다.
      node.setAttribute("rel", "noopener noreferrer");
    }
  });
}

registerHooks();

const POST_CONFIG: Config = {
  ALLOWED_TAGS: ["p", "br", "strong", "em", "a", "span", "img", "h2", "h3", "h4", "blockquote", "ul", "ol", "li", "hr", "details", "summary", "figure", "figcaption", "pre", "code", "del", "u"],
  ALLOWED_ATTR: ["href", "src", "alt", "class", "style", "title", "target", "rel", "data-align", "data-width", "data-wrap"],
};

const NAME_CONFIG: Config = {
  ALLOWED_TAGS: ["img", "span", "strong", "em"],
  ALLOWED_ATTR: ["src", "alt", "class", "title", "style"],
};

const EPISODE_CONFIG: Config = {
  ALLOWED_TAGS: ["p", "br", "strong", "em", "a", "span", "img", "h2", "h3", "h4", "blockquote", "ul", "ol", "li", "hr", "figure", "figcaption", "pre", "code", "del", "u", "sub", "sup", "div"],
  ALLOWED_ATTR: ["href", "src", "alt", "class", "style", "title", "target", "rel", "data-align", "data-width", "data-wrap", "data-spoiler"],
};

export function sanitizePost(html: string): string {
  return DOMPurify.sanitize(html, POST_CONFIG) as unknown as string;
}

export function sanitizeName(html: string): string {
  return DOMPurify.sanitize(html, NAME_CONFIG) as unknown as string;
}

export function sanitizeEpisode(html: string): string {
  return DOMPurify.sanitize(html, EPISODE_CONFIG) as unknown as string;
}

export function sanitizeBasic(html: string): string {
  return DOMPurify.sanitize(html, { ALLOWED_TAGS: ["img", "span"], ALLOWED_ATTR: ["src", "alt", "class", "title"] }) as unknown as string;
}

export function sanitizeSummary(html: string): string {
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: ["p", "br", "a", "span", "strong", "em", "img"],
    ALLOWED_ATTR: ["href", "class", "src", "alt", "title", "style"],
  }) as unknown as string;
}
