import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { CapabilityZone } from "../../shared/api/generated/model";
import i18n from "../../shared/i18n";
import { ZonesBlock } from "./PersonBlocks";

const zone = {
  id: "z1",
  code: "z-1",
  name: { ru: "Люди", uz: "Odamlar", en: "People" },
  role: "responsible",
} as unknown as CapabilityZone;

afterEach(cleanup);

describe.each(["ru", "uz", "en"])("ZonesBlock (%s)", (lng) => {
  beforeEach(() => {
    void i18n.changeLanguage(lng);
  });
  it("shows a zone without raw translation keys", () => {
    const { container } = render(<ZonesBlock title="T" known items={[zone]} />);
    expect(screen.getByTestId("cap-zones").querySelectorAll("li")).toHaveLength(1);
    expect(container.textContent).not.toContain("card.");
  });
});
