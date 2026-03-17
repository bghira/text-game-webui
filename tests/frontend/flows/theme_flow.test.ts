import {
  initThemeState,
  loadThemesFlow,
  applyThemeFlow,
  getThemeSettingFlow,
  themeFullFlow,
} from "../src/flow_helpers";
import type { ThemeEntry, ThemeState } from "../src/flow_helpers";

const BUILTIN_THEMES: ThemeEntry[] = [
  { value: "light", label: "Light", description: "Default light theme", source: "builtin" },
  { value: "dark", label: "Dark", description: "Dark theme", source: "builtin" },
];

describe("theme flow", () => {
  it("initializes theme state with default", () => {
    const state = initThemeState();
    expect(state.theme).toBe("light");
    expect(state.themes).toEqual([]);
  });

  it("initializes theme state with explicit value", () => {
    const state = initThemeState("dark");
    expect(state.theme).toBe("dark");
  });

  it("loads themes list from API", async () => {
    const seen: string[] = [];
    const fetcher = jest.fn(async (url: string) => {
      seen.push(url);
      return BUILTIN_THEMES;
    });

    const result = await loadThemesFlow(fetcher);
    expect(result.calls).toEqual(["/api/themes"]);
    expect(result.themes).toHaveLength(2);
    expect(result.themes[0].value).toBe("light");
    expect(result.themes[1].value).toBe("dark");
    expect(seen).toEqual(["/api/themes"]);
  });

  it("applies a valid theme and POSTs to server", async () => {
    const seen: Array<{ url: string; method?: string; body?: string }> = [];
    const fetcher = jest.fn(async (url: string, init?: { method?: string; body?: string }) => {
      seen.push({ url, method: init?.method, body: init?.body });
      return { theme: "dark" };
    });

    const state: ThemeState = {
      theme: "light",
      themes: BUILTIN_THEMES,
    };

    const result = await applyThemeFlow(fetcher, state, "dark");
    expect(result.state.theme).toBe("dark");
    expect(result.calls).toEqual(["/api/settings/theme"]);
    expect(seen).toHaveLength(1);
    expect(seen[0].method).toBe("POST");
    expect(JSON.parse(seen[0].body!)).toEqual({ theme: "dark" });
  });

  it("does not apply a theme not in the loaded list", async () => {
    const fetcher = jest.fn(async () => ({}));

    const state: ThemeState = {
      theme: "light",
      themes: BUILTIN_THEMES,
    };

    const result = await applyThemeFlow(fetcher, state, "nonexistent");
    expect(result.state.theme).toBe("light");
    expect(result.calls).toEqual([]);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("fetches current theme setting from server", async () => {
    const fetcher = jest.fn(async (url: string) => {
      return { theme: "dark" };
    });

    const result = await getThemeSettingFlow(fetcher);
    expect(result.calls).toEqual(["/api/settings/theme"]);
    expect(result.theme).toBe("dark");
  });

  it("runs full theme switch flow: load setting, load list, apply", async () => {
    let callIndex = 0;
    const responses: unknown[] = [
      { theme: "light" },   // GET /api/settings/theme
      BUILTIN_THEMES,       // GET /api/themes
      { theme: "dark" },    // POST /api/settings/theme
    ];

    const seen: string[] = [];
    const fetcher = jest.fn(async (url: string) => {
      seen.push(url);
      return responses[callIndex++];
    });

    const result = await themeFullFlow(fetcher, "dark");

    expect(result.calls).toEqual([
      "/api/settings/theme",
      "/api/themes",
      "/api/settings/theme",
    ]);
    expect(result.state.theme).toBe("dark");
    expect(result.state.themes).toHaveLength(2);
    expect(seen).toEqual([
      "/api/settings/theme",
      "/api/themes",
      "/api/settings/theme",
    ]);
  });

  it("full flow does not apply invalid theme", async () => {
    let callIndex = 0;
    const responses: unknown[] = [
      { theme: "light" },
      BUILTIN_THEMES,
    ];

    const fetcher = jest.fn(async (url: string) => {
      return responses[callIndex++];
    });

    const result = await themeFullFlow(fetcher, "nonexistent");

    // Only 2 calls: get setting + list; no POST because theme is invalid
    expect(result.calls).toEqual([
      "/api/settings/theme",
      "/api/themes",
    ]);
    expect(result.state.theme).toBe("light");
  });

  it("handles custom theme from pip package in theme list", async () => {
    const customThemes: ThemeEntry[] = [
      ...BUILTIN_THEMES,
      { value: "forest", label: "Forest", description: "A forest theme", source: "entry_point" },
    ];

    let callIndex = 0;
    const responses: unknown[] = [
      { theme: "light" },
      customThemes,
      { theme: "forest" },
    ];

    const fetcher = jest.fn(async () => responses[callIndex++]);

    const result = await themeFullFlow(fetcher, "forest");
    expect(result.state.theme).toBe("forest");
    expect(result.state.themes).toHaveLength(3);
  });

  it("handles local folder theme in theme list", async () => {
    const localThemes: ThemeEntry[] = [
      ...BUILTIN_THEMES,
      { value: "my-local", label: "My Local", description: "Local theme", source: "local" },
    ];

    const state: ThemeState = {
      theme: "light",
      themes: localThemes,
    };

    const fetcher = jest.fn(async () => ({ theme: "my-local" }));
    const result = await applyThemeFlow(fetcher, state, "my-local");
    expect(result.state.theme).toBe("my-local");
    expect(result.calls).toEqual(["/api/settings/theme"]);
  });

  it("preserves theme state when switching back to light", async () => {
    const state: ThemeState = {
      theme: "dark",
      themes: BUILTIN_THEMES,
    };

    const fetcher = jest.fn(async () => ({ theme: "light" }));
    const result = await applyThemeFlow(fetcher, state, "light");
    expect(result.state.theme).toBe("light");
  });
});
