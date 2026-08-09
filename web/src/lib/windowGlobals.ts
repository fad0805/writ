export type WindowWithGlobals = Window & {
  __serverLogo?: string;
  __emojiMap?: Record<string, string>;
  __localEmojiMap?: Record<string, string>;
};

export const serverWindow = (): WindowWithGlobals => window as WindowWithGlobals;
