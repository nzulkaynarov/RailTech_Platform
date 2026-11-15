import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { splitUnit, unitOf } from "../lib/unit";
import { UnitLabel } from "./UnitLabel";

describe("UnitLabel", () => {
  it("splits the unit after the last comma", () => {
    expect(splitUnit("Квота, шт.")).toEqual({ text: "Квота", unit: "шт." });
    expect(splitUnit("Цена закупки, USD")).toEqual({ text: "Цена закупки", unit: "USD" });
    expect(splitUnit("Срок")).toEqual({ text: "Срок", unit: null });
    expect(unitOf("Срок")).toBeUndefined();
  });

  it("shows the label without the unit but keeps it for screen readers", () => {
    render(
      <>
        <label htmlFor="q">
          <UnitLabel label="Квота, шт." />
        </label>
        <input id="q" />
      </>,
    );
    expect(screen.getByLabelText("Квота, шт.")).toBeInTheDocument();
    expect(screen.getByText(", шт.")).toHaveClass("pf-sr-only");
  });
});
