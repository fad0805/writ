export interface FluentEmojiItem {
  char: string;
  slug: string;
  name: string;
  group: string;
  aliases: string[];
}

export interface FluentEmojiGroup {
  name: string;
  emojis: FluentEmojiItem[];
}

const GROUP_NAMES: Record<string, string> = {
  "Smileys & Emotion": "표정",
  "People & Body": "사람·신체",
  "Component": "구성",
  "Animals & Nature": "동물·자연",
  "Food & Drink": "음식·음료",
  "Travel & Places": "여행·장소",
  "Activities": "활동",
  "Objects": "사물",
  "Symbols": "기호",
  "Flags": "깃발",
  "기타": "기타",
};

const TONE_SUFFIXES: { suffix: string; modifier: string; label: string }[] = [
  { suffix: "-medium-light", modifier: "\u{1F3FC}", label: "medium light" },
  { suffix: "-medium-dark", modifier: "\u{1F3FE}", label: "medium dark" },
  { suffix: "-light", modifier: "\u{1F3FB}", label: "light" },
  { suffix: "-medium", modifier: "\u{1F3FD}", label: "medium" },
  { suffix: "-dark", modifier: "\u{1F3FF}", label: "dark" },
];

function normalize(value: string) {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function addAliases(target: string[], values: string[]) {
  for (const value of values) {
    if (value && !target.includes(value)) target.push(value);
  }
}

type UnicodeEmoji = { emoji: string; name: string; slug: string };
type UnicodeGroup = { name: string; emojis: UnicodeEmoji[] };

function splitTone(slug: string) {
  if (slug.endsWith("-default")) {
    return { baseSlug: slug.slice(0, -"-default".length), tone: null };
  }
  for (const tone of TONE_SUFFIXES) {
    if (slug.endsWith(tone.suffix)) {
      return { baseSlug: slug.slice(0, -tone.suffix.length), tone };
    }
  }
  return { baseSlug: slug, tone: null };
}

let cache: Promise<FluentEmojiGroup[]> | null = null;

async function buildGroups(): Promise<FluentEmojiGroup[]> {
  const [unicodeData, fluentMeta] = await Promise.all([
    import("unicode-emoji-json/data-by-group.json") as Promise<{ default: UnicodeGroup[] }>,
    import("@fluentui-emoji/svg/metadata.json") as Promise<{
      default: { emojis: { slug: string; name: string; styles: string[] }[] };
    }>,
  ]);

  const byName = new Map<string, { char: string; group: string }>();
  const groupOrder: string[] = [];
  for (const group of unicodeData.default) {
    const label = GROUP_NAMES[group.name] || group.name;
    if (!groupOrder.includes(label)) groupOrder.push(label);
    for (const emoji of group.emojis) {
      byName.set(normalize(emoji.name), { char: emoji.emoji, group: label });
    }
  }

  const groups = new Map<string, FluentEmojiItem[]>();
  for (const meta of fluentMeta.default.emojis) {
    if (meta.styles.length > 0 && !meta.styles.includes("flat")) continue;
    const { baseSlug, tone } = splitTone(meta.slug);
    const base = byName.get(normalize(baseSlug));
    if (!base) continue;
    // ZWJ 조합에 피부톤을 단순히 덧붙이면 잘못된 문자이므로 건너뛴다.
    if (tone && base.char.includes("\u200d")) continue;

    const char = tone ? base.char + tone.modifier : base.char;
    const baseName = baseSlug.replace(/-/g, " ");
    const aliases: string[] = [];
    addAliases(aliases, [
      baseSlug,
      baseSlug.replace(/-/g, "_"),
      baseName,
      baseName.replace(/\s+/g, "_"),
      meta.name.toLowerCase(),
      meta.name.toLowerCase().replace(/\s+/g, "_"),
    ]);
    if (tone) {
      addAliases(aliases, [
        `${baseSlug}-${tone.label.replace(/\s+/g, "-")}`,
        `${baseSlug.replace(/-/g, "_")}_${tone.label.replace(/\s+/g, "_")}`,
        tone.label,
      ]);
    }

    const item: FluentEmojiItem = {
      char,
      slug: meta.slug,
      name: meta.name,
      group: base.group,
      aliases,
    };
    const list = groups.get(base.group) || [];
    list.push(item);
    groups.set(base.group, list);
  }

  const ordered: FluentEmojiGroup[] = [];
  for (const name of groupOrder) {
    const emojis = groups.get(name);
    if (emojis?.length) ordered.push({ name, emojis });
  }
  const extra = groups.get("기타");
  if (extra?.length) ordered.push({ name: "기타", emojis: extra });

  return ordered;
}

export function loadFluentEmojis() {
  if (!cache) cache = buildGroups();
  return cache;
}

const FLUENT_BASE = "https://cdn.jsdelivr.net/npm/@fluentui-emoji/svg@2.2.0/icons/flat";

export function fluentEmojiUrl(slug: string) {
  return `${FLUENT_BASE}/${slug}.svg`;
}
