import { describe, expect, it } from "vitest";

import { formatTimestamp } from "@/lib/format";

describe("formatTimestamp", () => {
  it("formats minute timestamps", () => {
    expect(formatTimestamp(70_000)).toBe("01:10");
  });

  it("formats hour timestamps", () => {
    expect(formatTimestamp(3_661_000)).toBe("01:01:01");
  });
});

