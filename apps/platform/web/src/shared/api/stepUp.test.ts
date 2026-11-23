import { afterEach, describe, expect, it } from "vitest";

import { forgetStepUp, freshStepUp, rememberStepUp } from "./stepUp";

describe("step-up token", () => {
  afterEach(forgetStepUp);

  it("is fresh for a few minutes and gone afterwards", () => {
    rememberStepUp("tok", 1_000);
    expect(freshStepUp(1_000 + 269_000)).toBe("tok");
    expect(freshStepUp(1_000 + 271_000)).toBeNull();
    expect(freshStepUp(1_000)).toBeNull();
  });

  it("is empty until a code is entered", () => {
    expect(freshStepUp()).toBeNull();
  });
});
