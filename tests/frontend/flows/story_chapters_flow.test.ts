import { storyStateFlow, sceneAndStylesFlow } from "../src/flow_helpers";

describe("story state flow", () => {
  test("fetches story state and chapter list", async () => {
    const fetcher = jest.fn(async (url: string) => {
      if (url.includes("/story")) {
        return {
          on_rails: true,
          story_outline: "A tale of two cities.",
          current_chapter: "Chapter 1: The Beginning",
          current_scene: "arrival",
          plot_threads: { revenge: "ongoing" },
          consequences: {},
          active_puzzle: null,
          active_minigame: null,
        };
      }
      if (url.includes("/chapters")) {
        return {
          on_rails: true,
          current_chapter: "Chapter 1",
          current_scene: "arrival",
          chapters: [
            { title: "Chapter 1: The Beginning", scenes: ["arrival", "market"] },
            { title: "Chapter 2: The Storm", scenes: ["storm-approach"] },
          ],
        };
      }
      return {};
    });

    const result = await storyStateFlow(fetcher, "camp-1");

    expect(result.calls).toHaveLength(2);
    expect(fetcher).toHaveBeenCalledTimes(2);

    const story = result.story as { on_rails: boolean; story_outline: string };
    expect(story.on_rails).toBe(true);
    expect(story.story_outline).toBe("A tale of two cities.");

    const chapters = result.chapters as { chapters: Array<{ title: string }> };
    expect(chapters.chapters).toHaveLength(2);
    expect(chapters.chapters[0].title).toContain("The Beginning");
  });

  test("empty story returns null fields", async () => {
    const fetcher = jest.fn(async () => ({
      on_rails: false,
      story_outline: null,
      current_chapter: null,
      current_scene: null,
      plot_threads: {},
      consequences: {},
      active_puzzle: null,
      active_minigame: null,
      chapters: [],
    }));

    const result = await storyStateFlow(fetcher, "camp-1");
    const story = result.story as { story_outline: null };
    expect(story.story_outline).toBeNull();
  });
});

describe("scene and literary styles flow", () => {
  test("fetches scene images and literary styles", async () => {
    const fetcher = jest.fn(async (url: string) => {
      if (url.includes("/scene-images")) {
        return { images: { "market-square": "https://example.com/market.png" } };
      }
      if (url.includes("/literary-styles")) {
        return { styles: { noir: "Dark and moody.", gothic: "Victorian horror." } };
      }
      return {};
    });

    const result = await sceneAndStylesFlow(fetcher, "camp-1");

    expect(result.calls).toHaveLength(2);
    expect(fetcher).toHaveBeenCalledTimes(2);

    const images = result.images as { images: Record<string, string> };
    expect(images.images["market-square"]).toBe("https://example.com/market.png");

    const styles = result.styles as { styles: Record<string, string> };
    expect(styles.styles.noir).toBe("Dark and moody.");
  });

  test("empty responses have empty objects", async () => {
    const fetcher = jest.fn(async () => ({ images: {}, styles: {} }));

    const result = await sceneAndStylesFlow(fetcher, "camp-1");
    const images = result.images as { images: Record<string, string> };
    expect(Object.keys(images.images)).toHaveLength(0);
  });
});
