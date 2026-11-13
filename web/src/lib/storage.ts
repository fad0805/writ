function getStorage(kind: "local" | "session"): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    const storage = kind === "local" ? window.localStorage : window.sessionStorage;
    if (!storage || typeof storage.getItem !== "function") return null;
    return storage;
  } catch {
    return null;
  }
}

export function storageGet(key: string): string | null {
  return getStorage("local")?.getItem(key) ?? null;
}

export function storageSet(key: string, value: string): void {
  try {
    getStorage("local")?.setItem(key, value);
  } catch {
    // Ignore quota/security errors; storage is an optional enhancement.
  }
}

export function storageRemove(key: string): void {
  try {
    getStorage("local")?.removeItem(key);
  } catch {
    // Ignore quota/security errors; storage is an optional enhancement.
  }
}

export function sessionGet(key: string): string | null {
  return getStorage("session")?.getItem(key) ?? null;
}

export function sessionSet(key: string, value: string): void {
  try {
    getStorage("session")?.setItem(key, value);
  } catch {
    // Ignore quota/security errors; storage is an optional enhancement.
  }
}

export function sessionRemove(key: string): void {
  try {
    getStorage("session")?.removeItem(key);
  } catch {
    // Ignore quota/security errors; storage is an optional enhancement.
  }
}
