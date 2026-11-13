import "@testing-library/jest-dom/vitest";

// Node 25 exposes its own localStorage/sessionStorage globals, and Vitest can
// leave them in place instead of jsdom's working Storage objects. Replace both
// with a small in-memory implementation so tests and app code get real methods.
class MemoryStorage implements Storage {
  private readonly store = new Map<string, string>();

  get length(): number {
    return this.store.size;
  }

  clear(): void {
    this.store.clear();
  }

  getItem(key: string): string | null {
    return this.store.get(String(key)) ?? null;
  }

  key(index: number): string | null {
    return Array.from(this.store.keys())[index] ?? null;
  }

  removeItem(key: string): void {
    this.store.delete(String(key));
  }

  setItem(key: string, value: string): void {
    this.store.set(String(key), String(value));
  }
}

for (const name of ["localStorage", "sessionStorage"] as const) {
  const storage = new MemoryStorage();
  Object.defineProperty(window, name, {
    value: storage,
    configurable: true,
    writable: true,
  });
  Object.defineProperty(globalThis, name, {
    value: storage,
    configurable: true,
    writable: true,
  });
}
