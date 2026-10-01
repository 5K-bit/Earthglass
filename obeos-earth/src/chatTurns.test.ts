import { describe, it, expect } from "vitest";
import { turnsFrom, noticeFrom, sessionFrom, isSilent } from "./chatTurns";

describe("chat turn shaping", () => {
  it("renders server history, which carries other surfaces' turns too", () => {
    const turns = turnsFrom({
      messages: [
        { event_id: "a", role: "user", text: "where am I?", agent: "operator" },
        {
          event_id: "b",
          role: "assistant",
          text: "Cincinnati.",
          agent: "daise",
        },
      ],
    });
    expect(turns.map((t) => [t.role, t.text])).toEqual([
      ["user", "where am I?"],
      ["assistant", "Cincinnati."],
    ]);
    expect(turns[1].agent).toBe("daise");
  });

  it("drops bodyless events and falls back on unknown roles and ids", () => {
    const turns = turnsFrom({
      messages: [
        { event_id: "a", role: "user", text: "   " },
        { role: "wat", text: "kept" },
        { event_id: "c", role: "system", text: "note" },
      ],
    });
    expect(turns).toHaveLength(2);
    expect(turns[0]).toMatchObject({
      role: "assistant",
      text: "kept",
      id: "turn-1",
    });
    expect(turns[1].role).toBe("system");
  });

  it("survives a malformed payload instead of throwing", () => {
    expect(turnsFrom({})).toEqual([]);
    expect(turnsFrom({ messages: "nope" })).toEqual([]);
    expect(turnsFrom({ messages: [null as never, 7 as never] })).toEqual([]);
  });

  it("names the cross-process lease, because that one is the operator's to resolve", () => {
    expect(
      noticeFrom({
        status: "error",
        error_type: "session_busy",
        error: "busy",
      }),
    ).toContain("Another surface is mid-turn");
  });

  it("surfaces a failure reason, and says something when there is none", () => {
    expect(noticeFrom({ status: "error", error: "model unavailable" })).toBe(
      "model unavailable",
    );
    expect(noticeFrom({ status: "error" })).toBe("That turn did not complete.");
    expect(
      noticeFrom({ status: "complete", result: { error: "partial" } }),
    ).toBe("partial");
    expect(
      noticeFrom({ status: "complete", result: { response: "fine" } }),
    ).toBe("");
  });

  it("keeps the shared session and does not lose it to a blank reply", () => {
    expect(sessionFrom({ session_id: "s2" }, "s1")).toBe("s2");
    expect(sessionFrom({}, "s1")).toBe("s1");
    expect(sessionFrom({ session_id: "" }, "s1")).toBe("s1");
  });

  it("detects a reply with nothing to show, so the panel can admit it", () => {
    expect(isSilent({ status: "complete", messages: [] })).toBe(true);
    expect(isSilent({ status: "complete", result: { response: "hi" } })).toBe(
      false,
    );
    expect(
      isSilent({ messages: [{ event_id: "a", role: "user", text: "hi" }] }),
    ).toBe(false);
  });
});
