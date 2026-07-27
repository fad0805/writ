const LINES_PER_PAGE = 20;

export function splitIntoPages(html: string): string[] {
  if (!html) return [""];
  const hasPTags = /<p[\s>]/i.test(html);
  const hasBrTags = /<br\s*\/?>/i.test(html);

  let lines: string[];
  if (hasPTags) {
    lines = html.split(/<\/p>/i).filter(s => s.trim());
  } else if (hasBrTags) {
    lines = html.split(/<br\s*\/?>/i);
  } else {
    lines = html.split("\n");
  }

  const pages: string[] = [];
  let current: string[] = [];
  let lineCount = 0;
  const closeTag = hasPTags ? "</p>" : "";

  for (const line of lines) {
    current.push(line + closeTag);
    lineCount++;
    if (lineCount >= LINES_PER_PAGE) {
      pages.push(current.join(""));
      current = [];
      lineCount = 0;
    }
  }

  const remaining = current.join("");
  if (remaining.trim()) pages.push(remaining);
  if (pages.length === 0) pages.push("");
  return pages;
}

export function joinPages(pages: string[]): string {
  return pages.join("");
}
