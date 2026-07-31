import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll } from "vitest";
import { cleanup } from "@testing-library/react";
import { server } from "./msw/server";
import { resetFixtures } from "./msw/fixtures";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));

afterEach(() => {
  cleanup();
  server.resetHandlers();
  resetFixtures();
  localStorage.clear();
  sessionStorage.clear();
});

afterAll(() => server.close());

// jsdom lacks layout APIs that @tanstack/react-virtual and the tab strip rely on.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
if (!("ResizeObserver" in globalThis)) {
  (globalThis as Record<string, unknown>).ResizeObserver = ResizeObserverStub;
}
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}
if (!window.scrollTo) {
  window.scrollTo = (() => {}) as typeof window.scrollTo;
}
