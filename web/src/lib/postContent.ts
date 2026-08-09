import { PostData } from "@/lib/api";
import { CustomEmoji, renderCustomEmojis } from "@/lib/emojis";

export function formatRelative(iso: string, now: number = Date.now()): string {
  const diff = new Date(iso).getTime() - now;
  const abs = Math.abs(diff);
  if (abs < 60000) return `${Math.floor(abs / 1000)}초`;
  if (abs < 3600000) return `${Math.floor(abs / 60000)}분 ${Math.floor((abs % 60000) / 1000)}초`;
  if (abs < 86400000) return `${Math.floor(abs / 3600000)}시간`;
  return `${Math.floor(abs / 86400000)}일`;
}

export function rewriteLinks(text: string): string {
  const protectedTags: string[] = [];
  text = text.replace(/<a\b[^>]*>[\s\S]*?<\/a>/gi, (m) => {
    protectedTags.push(m);
    return `\x00LINK_${protectedTags.length - 1}\x00`;
  });

  text = text.replace(
    /(^|>|\s)#([\p{L}\p{N}_]+)/gu,
    (_m, before, tag) => {
      return `${before}<a href="/explore?q=%23${encodeURIComponent(tag)}" class="hashtag-link">#${tag}</a>`;
    }
  );

  text = text.replace(
    /(^|>| |\s)(https?:\/\/[^\s<>"')\]]+)/g,
    (_m: string, before: string, url: string) => {
      const isLocal = typeof window !== "undefined" && url.startsWith(window.location.origin);
      const targetUrl = isLocal ? url.replace(window.location.origin, "") : url;
      let display = url.replace(/^https?:\/\//, "");
      if (display.length > 40) display = display.slice(0, 37) + "...";
      return `${before}<a href="${targetUrl}"${isLocal ? "" : ' target="_blank" rel="noopener noreferrer"'}>${display}</a>`;
    }
  );

  text = text.replace(/\x00LINK_(\d+)\x00/g, (_, i) => protectedTags[parseInt(i)]);
  return text;
}

export function buildPostContentHtml(post: PostData, emojiList: CustomEmoji[]): string {
  let html = post.content || "";

  const uniqueEmojis = Array.from(
    new Map(emojiList.map(e => [e.keyword, e])).values()
  );

  // Strip "RE: https://..." from quote posts
  html = html.replace(/(?:<span[^>]*>)?[\s\n]*RE:[\s\n]*(?:<a[^>]*>.*?<\/a>|https?:\/\/[^\s<>]+)[\s\n]*(?:<\/span>)?(?:[\s\n]*<br\s*\/?>)*/gi, '');

  // 인용(quote) 대상 URL이 본문에 텍스트 링크로 남아있으면 제거 (인용 카드와 중복 렌더링 방지)
  if (post.quote_of_id || post.quote_of_ap_id) {
    const quoteUrls = new Set([
      post.quote_of_ap_id,
      post.quoted_post?.url,
      post.quoted_post?.ap_id,
    ].filter((u): u is string => Boolean(u)));
    for (const qUrl of quoteUrls) {
      const esc = qUrl.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      html = html.replace(new RegExp(`<a\\b[^>]*?\\bhref="${esc}"[^>]*>[\\s\\S]*?<\\/a>`, "gi"), "");
      html = html.replace(new RegExp(esc, "g"), "");
    }
  }

  // 본문에서 series, episode 접두사 라인을 앞뒤 공백/줄바꿈 포함하여 완전히 삭제
  html = html.replace(/(?:<br\s*\/?>|\n|^)\s*(?:series|episode):\s*(?:<a[^>]*>.*?<\/a>|https?:\/\/[^\s<>]+)\s*(?:<br\s*\/?>|\n|$)/gi, '\n');

  if (/<\/?[a-zA-Z]+[\s\/>]/.test(html) || /&[a-z]+;/.test(html)) {
    html = html.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&');
  } else {
    html = html.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  const codeBlocks: string[] = [];
  html = html.replace(/```(\w*)\r?\n([\s\S]*?)```/g, (_m, _lang, code) => {
    const idx = codeBlocks.length;
    codeBlocks.push(`<pre><code>${code.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/\s+$/, '')}</code></pre>`);
    return `\x00CODEBLOCK_${idx}\x00`;
  });
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
  html = html.replace(/`(.+?)`/g, '<code>$1</code>');
  html = html.replace(/\n/g, '<br>');
  codeBlocks.forEach((block, i) => {
    html = html.replace(`\x00CODEBLOCK_${i}\x00`, block);
  });
  html = renderCustomEmojis(html, uniqueEmojis);
  html = rewriteLinks(html);
  return html;
}
