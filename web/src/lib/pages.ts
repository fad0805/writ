const LINES_PER_PAGE = 20;

export function splitIntoPages(html: string): string[] {
  if (!html) return [""];
  const blocks = html.split(/(<br\s*\/?>|\n)/i);
  const pages: string[] = [];
  let current: string[] = [];
  let lineCount = 0;

  for (const block of blocks) {
    if (/^<br\s*\/?>$/i.test(block) || block === "\n") {
      lineCount++;
      current.push("\n");
      if (lineCount >= LINES_PER_PAGE) {
        pages.push(current.join("").replace(/\n$/, ""));
        current = [];
        lineCount = 0;
      }
    } else {
      current.push(block);
    }
  }

  const remaining = current.join("");
  if (remaining.trim()) pages.push(remaining);
  if (pages.length === 0) pages.push("");
  return pages;
}

export function joinPages(pages: string[]): string {
  return pages.join("\n");
}
