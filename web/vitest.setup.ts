import "@testing-library/jest-dom/vitest";

// jsdom 29 + vitest 4: localStorage is a plain object without Storage prototype methods.
// Fix it by restoring the Storage prototype.
if (typeof window.localStorage === "object" && !window.localStorage.getItem) {
  Object.setPrototypeOf(window.localStorage, Storage.prototype);
}
