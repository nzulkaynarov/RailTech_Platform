import { describe, expect, it } from "vitest";

import { ApiError } from "../../api/http";
import { transferNeeded } from "./transfer";

describe("transferNeeded", () => {
  it.each([
    ["active leads with count", new ApiError(409, "user_has_active_leads", "x", { count: 3 }), 3],
    ["active leads without count", new ApiError(409, "user_has_active_leads", "x"), 0],
    [
      "inactive colleague chosen",
      new ApiError(422, "validation_failed", "x", { field: "transfer_to_user_id" }),
      0,
    ],
    ["other conflict", new ApiError(409, "last_admin", "x"), null],
    ["network error", new Error("boom"), null],
  ])("%s", (_, error, expected) => {
    expect(transferNeeded(error)).toBe(expected);
  });
});
