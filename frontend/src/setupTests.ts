import "@testing-library/jest-dom/vitest";

// jsdom does not implement scrollIntoView; ChatWindow calls it on every render.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}
