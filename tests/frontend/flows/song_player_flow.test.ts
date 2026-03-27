import {
  initSongQueueState,
  pushSong,
  songPrev,
  songNext,
  currentSong,
  songEmbedUrl,
  SongNotificationEvent,
} from "../src/flow_helpers";

function makeSong(id: string, title: string, sender = "", caption = ""): SongNotificationEvent["payload"] {
  return {
    video_id: id,
    url: `https://www.youtube.com/watch?v=${id}`,
    title,
    sender,
    caption,
  };
}

describe("song player queue", () => {
  test("initSongQueueState returns empty state", () => {
    const state = initSongQueueState();
    expect(state.queue).toEqual([]);
    expect(state.index).toBe(-1);
    expect(currentSong(state)).toBeNull();
    expect(songEmbedUrl(state)).toBe("");
  });

  test("pushSong adds song and auto-advances to it", () => {
    let state = initSongQueueState();
    const song1 = makeSong("abc123def45", "Heaven or Las Vegas", "Simone");

    state = pushSong(state, song1);
    expect(state.queue).toHaveLength(1);
    expect(state.index).toBe(0);
    expect(currentSong(state)).toEqual(song1);
    expect(songEmbedUrl(state)).toBe("https://www.youtube.com/embed/abc123def45?autoplay=1&rel=0");
  });

  test("pushSong skips back-to-back duplicates", () => {
    let state = initSongQueueState();
    const song = makeSong("abc123def45", "Song A");

    state = pushSong(state, song);
    state = pushSong(state, song);
    expect(state.queue).toHaveLength(1);
    expect(state.index).toBe(0);
  });

  test("pushSong allows same song after a different one", () => {
    let state = initSongQueueState();
    const songA = makeSong("aaa11111111", "Song A");
    const songB = makeSong("bbb22222222", "Song B");

    state = pushSong(state, songA);
    state = pushSong(state, songB);
    state = pushSong(state, songA);
    expect(state.queue).toHaveLength(3);
    expect(state.index).toBe(2);
    expect(currentSong(state)!.video_id).toBe("aaa11111111");
  });

  test("prev/next navigation", () => {
    let state = initSongQueueState();
    const songA = makeSong("aaa11111111", "Song A", "Alice");
    const songB = makeSong("bbb22222222", "Song B", "Bob");
    const songC = makeSong("ccc33333333", "Song C", "Charlie", "This one hits.");

    state = pushSong(state, songA);
    state = pushSong(state, songB);
    state = pushSong(state, songC);
    expect(state.index).toBe(2); // auto-advanced to latest

    state = songPrev(state);
    expect(state.index).toBe(1);
    expect(currentSong(state)!.title).toBe("Song B");

    state = songPrev(state);
    expect(state.index).toBe(0);
    expect(currentSong(state)!.title).toBe("Song A");

    // Can't go past beginning
    state = songPrev(state);
    expect(state.index).toBe(0);

    state = songNext(state);
    expect(state.index).toBe(1);

    state = songNext(state);
    expect(state.index).toBe(2);

    // Can't go past end
    state = songNext(state);
    expect(state.index).toBe(2);
  });

  test("songEmbedUrl builds correct YouTube embed URL", () => {
    let state = initSongQueueState();
    state = pushSong(state, makeSong("dQw4w9WgXcQ", "Never Gonna Give You Up"));
    expect(songEmbedUrl(state)).toBe("https://www.youtube.com/embed/dQw4w9WgXcQ?autoplay=1&rel=0");
  });

  test("song metadata includes sender and caption", () => {
    let state = initSongQueueState();
    const song = makeSong("xyz98765432", "Enjoy the Silence", "Depeche Mode NPC", "Words are very unnecessary.");
    state = pushSong(state, song);

    const current = currentSong(state)!;
    expect(current.sender).toBe("Depeche Mode NPC");
    expect(current.caption).toBe("Words are very unnecessary.");
    expect(current.url).toBe("https://www.youtube.com/watch?v=xyz98765432");
  });
});
