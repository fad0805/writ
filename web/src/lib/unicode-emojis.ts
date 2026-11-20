export interface UnicodeEmojiItem {
  char: string;
  name: string;
  group: string;
  aliases: string[];
}

export interface UnicodeEmojiGroup {
  name: string;
  emojis: UnicodeEmojiItem[];
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

const TONES: { modifier: string; label: string }[] = [
  { modifier: "\u{1F3FB}", label: "light" },
  { modifier: "\u{1F3FC}", label: "medium light" },
  { modifier: "\u{1F3FD}", label: "medium" },
  { modifier: "\u{1F3FE}", label: "medium dark" },
  { modifier: "\u{1F3FF}", label: "dark" },
];

type RawEmoji = { emoji: string; name: string; slug: string; skin_tone_support?: boolean };
type RawGroup = { name: string; emojis: RawEmoji[] };

function addAliases(target: string[], values: string[]) {
  for (const value of values) {
    if (value && !target.includes(value)) target.push(value);
  }
}

let cache: Promise<UnicodeEmojiGroup[]> | null = null;

async function buildGroups(): Promise<UnicodeEmojiGroup[]> {
  const data = (await import("unicode-emoji-json/data-by-group.json")) as { default: RawGroup[] };
  const groups: UnicodeEmojiGroup[] = [];

  for (const group of data.default) {
    const label = GROUP_NAMES[group.name] || group.name;
    const items: UnicodeEmojiItem[] = [];

    for (const emoji of group.emojis) {
      const aliases: string[] = [];
      addAliases(aliases, [
        emoji.slug,
        emoji.slug.replace(/_/g, "-"),
        emoji.name.toLowerCase(),
        emoji.name.toLowerCase().replace(/\s+/g, "_"),
      ]);

      items.push({
        char: emoji.emoji,
        name: emoji.name,
        group: label,
        aliases,
      });

      // 피부톤 변형. ZWJ 조합은 수정자 위치가 복잡해 건너뛴다.
      if (!emoji.skin_tone_support || emoji.emoji.includes("\u200d")) continue;
      for (const tone of TONES) {
        const toneAliases: string[] = [];
        addAliases(toneAliases, [
          ...aliases,
          `${emoji.slug}_${tone.label.replace(/\s+/g, "_")}`,
          `${emoji.slug.replace(/_/g, "-")}-${tone.label.replace(/\s+/g, "-")}`,
          tone.label,
        ]);
        items.push({
          char: emoji.emoji + tone.modifier,
          name: `${emoji.name} (${tone.label})`,
          group: label,
          aliases: toneAliases,
        });
      }
    }

    if (items.length > 0) groups.push({ name: label, emojis: items });
  }

  return groups;
}

export function loadUnicodeEmojis() {
  if (!cache) cache = buildGroups();
  return cache;
}
