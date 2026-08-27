import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { runInThisContext } from "node:vm";
import { JSDOM } from "jsdom";

if (process.argv.length < 3) {
  console.error("usage: node tests/mermaid_render.mjs diagram.mmd");
  process.exit(2);
}

const require = createRequire(import.meta.url);
const mermaidBundle = require.resolve("mermaid/dist/mermaid.min.js");

const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", {
  pretendToBeVisual: true,
});
globalThis.window = dom.window;
globalThis.document = dom.window.document;
Object.defineProperty(globalThis, "navigator", {
  value: dom.window.navigator,
  configurable: true,
});
globalThis.DOMParser = dom.window.DOMParser;
globalThis.XMLSerializer = dom.window.XMLSerializer;
globalThis.SVGElement = dom.window.SVGElement;
globalThis.Element = dom.window.Element;
globalThis.Node = dom.window.Node;
globalThis.MutationObserver = dom.window.MutationObserver;
globalThis.requestAnimationFrame = dom.window.requestAnimationFrame;

class FakeCSSStyleSheet {
  constructor() {
    this._rules = [];
  }
  get cssRules() {
    return this._rules;
  }
  insertRule(css, idx) {
    const rule = { cssText: String(css) };
    const index = idx ?? 0;
    this._rules.splice(index, 0, rule);
    return index;
  }
  replaceSync() {}
  deleteRule() {}
  get cssText() {
    return "";
  }
}
globalThis.CSSStyleSheet = FakeCSSStyleSheet;
dom.window.CSSStyleSheet = FakeCSSStyleSheet;

const measure = (el) => {
  const text = (el.textContent || "").trim();
  const size =
    parseInt((el.getAttribute && el.getAttribute("font-size")) || "16", 10) ||
    16;
  return 0.6 * size * text.length + 10;
};
const win = dom.window;
win.SVGElement.prototype.getBBox = function getBBox() {
  return { x: 0, y: 0, width: Math.max(measure(this), 30), height: 22 };
};
win.SVGElement.prototype.getComputedTextLength = function getComputedTextLength() {
  return measure(this);
};
win.SVGElement.prototype.getTotalLength = function getTotalLength() {
  return 200;
};

if (!document.fonts) {
  document.fonts = { forEach() {}, check() { return true; } };
}
if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false,
    media: query,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    onchange: null,
    dispatchEvent() { return false; },
  });
}

runInThisContext(readFileSync(mermaidBundle, "utf8"), {
  filename: "mermaid.min.js",
});
const mermaid = globalThis.mermaid;
if (!mermaid) {
  console.error("mermaid bundle did not define the global API");
  process.exit(3);
}

await mermaid.initialize({ startOnLoad: false, securityLevel: "loose" });

try {
  const { svg } = await mermaid.render(
    "mmd_graph",
    readFileSync(process.argv[2], "utf8"),
  );
  if (!svg || !svg.includes("<svg")) {
    console.error("render produced no <svg>");
    process.exit(1);
  }
  console.log(svg.length);
} catch (error) {
  console.error(`render failed: ${error.message}`);
  process.exit(1);
}