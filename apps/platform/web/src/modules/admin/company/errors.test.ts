import { describe, expect, it } from "vitest";

import { ApiError } from "../../../shared/api/errors";
import { numberingErrorKey } from "./errors";

const fail = (details: Record<string, unknown>) =>
  new ApiError(422, "VALIDATION_FAILED", "x", "bff", details);

describe("numberingErrorKey", () => {
  it("names the ticket label error separately from the taken prefix", () => {
    expect(numberingErrorKey("type_labels", fail({ reason: "ticket_label_invalid" }))).toBe(
      "numbering.ticketLabelInvalid",
    );
    expect(numberingErrorKey("prefix", fail({}))).toBe("numbering.prefixTaken");
    expect(numberingErrorKey("pattern", fail({}))).toBe("numbering.maskInvalid");
  });
});
