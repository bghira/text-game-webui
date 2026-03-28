import { puzzleFlow, minigameFlow } from "../src/flow_helpers";

describe("puzzle flow", () => {
  test("gets hint and submits answer", async () => {
    const fetcher = jest.fn(async (url: string, init?: { method?: string; body?: string }) => {
      if (url.includes("/puzzle/hint")) {
        return { hint: "Look behind the painting.", note: "" };
      }
      if (url.includes("/puzzle/answer")) {
        return { correct: true, feedback: "Well done!", solved: true };
      }
      return {};
    });

    const result = await puzzleFlow(fetcher, "camp-1", "the hidden key");

    expect(result.calls).toHaveLength(2);

    const hint = result.hint as { hint: string };
    expect(hint.hint).toBe("Look behind the painting.");

    const answer = result.answerResult as { correct: boolean; solved: boolean };
    expect(answer.correct).toBe(true);
    expect(answer.solved).toBe(true);
  });

  test("answer payload includes the answer string", async () => {
    const fetcher = jest.fn(async () => ({ hint: null, correct: false, solved: false }));

    await puzzleFlow(fetcher, "camp-1", "42");

    const answerCall = fetcher.mock.calls[1] as unknown as [string, { body: string }];
    const body = JSON.parse(answerCall[1].body);
    expect(body.answer).toBe("42");
  });
});

describe("minigame flow", () => {
  test("gets board and submits move", async () => {
    const fetcher = jest.fn(async (url: string) => {
      if (url.includes("/minigame/board")) {
        return {
          board: { grid: [["X", "O", ""], ["", "X", ""], ["", "", ""]], turn: "O" },
          note: "",
        };
      }
      if (url.includes("/minigame/move")) {
        return { valid: true, message: "Move accepted.", finished: false };
      }
      return {};
    });

    const result = await minigameFlow(fetcher, "camp-1", "e2e4");

    expect(result.calls).toHaveLength(2);

    const board = result.board as { board: { turn: string } };
    expect(board.board.turn).toBe("O");

    const move = result.moveResult as { valid: boolean; finished: boolean };
    expect(move.valid).toBe(true);
    expect(move.finished).toBe(false);
  });

  test("move payload includes the move string", async () => {
    const fetcher = jest.fn(async () => ({ board: null, valid: false, finished: false }));

    await minigameFlow(fetcher, "camp-1", "d7d5");

    const moveCall = fetcher.mock.calls[1] as unknown as [string, { body: string }];
    const body = JSON.parse(moveCall[1].body);
    expect(body.move).toBe("d7d5");
  });

  test("no active minigame returns null board", async () => {
    const fetcher = jest.fn(async () => ({ board: null, note: "No active minigame." }));

    const result = await minigameFlow(fetcher, "camp-1", "noop");
    const board = result.board as { board: null; note: string };
    expect(board.board).toBeNull();
    expect(board.note).toBe("No active minigame.");
  });
});
