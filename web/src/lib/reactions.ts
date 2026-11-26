/** 서버별 커스텀 이모지 배지 키: `:shortcode:@domain` (로컬은 `:shortcode:`). */

export function parseReactionKey(key: string): { reaction: string; domain: string } {
  if (key.includes("@")) {
    const at = key.lastIndexOf("@");
    const reaction = key.slice(0, at);
    const domain = key.slice(at + 1);
    if (domain && reaction.startsWith(":") && reaction.endsWith(":")) {
      return { reaction, domain };
    }
  }
  return { reaction: key, domain: "" };
}

export function domainFromHandle(handle?: string): string {
  if (!handle || !handle.includes("@")) return "";
  return handle.slice(handle.lastIndexOf("@") + 1).toLowerCase();
}

export function emojiKeyword(reaction: string): string {
  return reaction.startsWith(":") && reaction.endsWith(":") ? reaction.slice(1, -1) : reaction;
}
