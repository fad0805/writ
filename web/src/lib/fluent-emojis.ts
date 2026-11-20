export interface FluentEmojiItem {
  char: string;
  slug?: string;
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
};

const TONES: { suffix: string; modifier: string; label: string }[] = [
  { suffix: "medium-light", modifier: "\u{1F3FC}", label: "medium light" },
  { suffix: "medium-dark", modifier: "\u{1F3FE}", label: "medium dark" },
  { suffix: "light", modifier: "\u{1F3FB}", label: "light" },
  { suffix: "medium", modifier: "\u{1F3FD}", label: "medium" },
  { suffix: "dark", modifier: "\u{1F3FF}", label: "dark" },
];

type UnicodeEmoji = { emoji: string; name: string; slug: string; skin_tone_support?: boolean };
type UnicodeGroup = { name: string; emojis: UnicodeEmoji[] };

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

let cache: Promise<FluentEmojiGroup[]> | null = null;

async function buildGroups(): Promise<FluentEmojiGroup[]> {
  const [unicodeData, fluentMeta] = await Promise.all([
    import("unicode-emoji-json/data-by-group.json") as Promise<{ default: UnicodeGroup[] }>,
    import("@fluentui-emoji/svg/metadata.json") as Promise<{
      default: { emojis: { slug: string; name: string; styles: string[] }[] };
    }>,
  ]);

  // Fluent 슬러그 집합. 국가기는 Fluent에 없으므로 여기서 걸러진다.
  const fluentSlugs = new Set(
    fluentMeta.default.emojis
      .filter((emoji) => emoji.styles.length === 0 || emoji.styles.includes("flat"))
      .map((emoji) => emoji.slug),
  );

  const ordered: FluentEmojiGroup[] = [];
  for (const group of unicodeData.default) {
    const label = GROUP_NAMES[group.name] || group.name;
    const items: FluentEmojiItem[] = [];

    for (const emoji of group.emojis) {
      const baseAliases: string[] = [];
      addAliases(baseAliases, [
        emoji.slug,
        emoji.slug.replace(/_/g, "-"),
        emoji.name.toLowerCase(),
        emoji.name.toLowerCase().replace(/\s+/g, "_"),
      ]);

      const baseSlug = normalize(emoji.name);
      const defaultSlug = emoji.skin_tone_support ? `${baseSlug}-default` : baseSlug;
      let slug: string | undefined;
      if (fluentSlugs.has(defaultSlug)) slug = defaultSlug;
      else if (fluentSlugs.has(baseSlug)) slug = baseSlug;

      items.push({
        char: emoji.emoji,
        slug,
        name: emoji.name,
        group: label,
        aliases: baseAliases,
      });

      // 피부톤 변형. ZWJ 조합은 보정이 복잡해 건너뛴다.
      if (!emoji.skin_tone_support || emoji.emoji.includes("\u200d")) continue;
      for (const tone of TONES) {
        const toneSlug = `${baseSlug}-${tone.suffix}`;
        if (!fluentSlugs.has(toneSlug)) continue;
        const aliases: string[] = [];
        addAliases(aliases, [
          ...baseAliases,
          toneSlug,
          toneSlug.replace(/-/g, "_"),
          tone.label,
        ]);
        items.push({
          char: emoji.emoji + tone.modifier,
          slug: toneSlug,
          name: `${emoji.name} (${tone.label})`,
          group: label,
          aliases,
        });
      }
    }

    if (items.length > 0) ordered.push({ name: label, emojis: items });
  }

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
