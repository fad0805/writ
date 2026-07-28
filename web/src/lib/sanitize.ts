import DOMPurify from "dompurify";

const POST_CONFIG: DOMPurify.Config = {
  ALLOWED_TAGS: ["p", "br", "strong", "em", "a", "span", "img", "h2", "h3", "h4", "blockquote", "ul", "ol", "li", "hr", "details", "summary", "figure", "figcaption", "pre", "code", "del", "u"],
  ALLOWED_ATTR: ["href", "src", "alt", "class", "style", "title", "target", "rel", "data-align", "data-width", "data-wrap"],
};

const NAME_CONFIG: DOMPurify.Config = {
  ALLOWED_TAGS: ["img", "span", "strong", "em"],
  ALLOWED_ATTR: ["src", "alt", "class", "title", "style"],
};

const EPISODE_CONFIG: DOMPurify.Config = {
  ALLOWED_TAGS: ["p", "br", "strong", "em", "a", "span", "img", "h2", "h3", "h4", "blockquote", "ul", "ol", "li", "hr", "figure", "figcaption", "pre", "code", "del", "u", "sub", "sup"],
  ALLOWED_ATTR: ["href", "src", "alt", "class", "style", "title", "target", "rel", "data-align", "data-width", "data-wrap"],
};

export function sanitizePost(html: string): string {
  return DOMPurify.sanitize(html, POST_CONFIG as any) as unknown as string;
}

export function sanitizeName(html: string): string {
  return DOMPurify.sanitize(html, NAME_CONFIG as any) as unknown as string;
}

export function sanitizeEpisode(html: string): string {
  return DOMPurify.sanitize(html, EPISODE_CONFIG as any) as unknown as string;
}

export function sanitizeBasic(html: string): string {
  return DOMPurify.sanitize(html, { ALLOWED_TAGS: ["img", "span"], ALLOWED_ATTR: ["src", "alt", "class", "title"] } as any) as unknown as string;
}

export function sanitizeSummary(html: string): string {
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: ["p", "br", "a", "span", "strong", "em", "img"],
    ALLOWED_ATTR: ["href", "class", "src", "alt", "title", "style"],
  } as any) as unknown as string;
}
