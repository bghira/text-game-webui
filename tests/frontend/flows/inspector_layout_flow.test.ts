import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const appCss = readFileSync(resolve(process.cwd(), "../../app/static/css/app.css"), "utf8");

function cssBlock(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = appCss.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`));
  if (!match) {
    throw new Error(`Missing CSS block for ${selector}`);
  }
  return match[1];
}

describe("debug inspector layout", () => {
  test("the inspector panel owns overflow instead of expanding the viewport shell", () => {
    const block = cssBlock(".inspector-panel");
    expect(block).toContain("max-height: min(42vh, 34rem)");
    expect(block).toContain("overflow-y: auto");
    expect(block).toContain("overscroll-behavior: contain");
    expect(block).toContain("scroll-padding-bottom: 0.75rem");
    expect(block).toContain("-webkit-overflow-scrolling: touch");
  });

  test("the tab row stays available while long debug tabs scroll", () => {
    const block = cssBlock(".tab-row");
    expect(block).toContain("position: sticky");
    expect(block).toContain("top: 0");
  });

  test("history rows use the shared inspector scroller so mobile can reach the final turn", () => {
    const block = cssBlock(".turn-history-list");
    expect(block).toContain("max-height: none");
    expect(block).toContain("overflow: visible");
    expect(block).toContain("padding-bottom: 0.35rem");
  });
});
