// Vitest setup: polyfills + global test utilities for the jsdom environment.
// Loaded via setupFiles in vitest.config.ts.

import "@testing-library/jest-dom";

// Recharts' ResponsiveContainer uses ResizeObserver, which jsdom doesn't ship.
// Polyfill with a minimal stub so component renders don't crash in unit tests.
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

if (typeof globalThis.ResizeObserver === "undefined") {
  // @ts-expect-error - jsdom doesn't ship ResizeObserver; assigning the stub.
  globalThis.ResizeObserver = ResizeObserverStub;
}

// Recharts' ResponsiveContainer measures the parent via getBoundingClientRect;
// jsdom returns all-zero, so the chart renders at width/height 0 and skips
// drawing dots/lines. Override BCR globally to return a non-trivial box so
// chart components actually emit SVG geometry under test.
if (typeof Element !== "undefined") {
  Element.prototype.getBoundingClientRect = function () {
    return {
      x: 0,
      y: 0,
      top: 0,
      left: 0,
      right: 800,
      bottom: 400,
      width: 800,
      height: 400,
      toJSON() {
        return this;
      },
    } as DOMRect;
  };
}

// matchMedia is also commonly missing in jsdom; some chart libs query it.
if (typeof window !== "undefined" && typeof window.matchMedia === "undefined") {
  // @ts-expect-error - jsdom doesn't ship matchMedia; assigning a stub.
  window.matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  });
}
