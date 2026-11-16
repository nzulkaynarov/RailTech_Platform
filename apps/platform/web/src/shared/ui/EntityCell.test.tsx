import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { entityInitials as initialsOf } from "../lib/initials";

import { CompanyCell, ItemCell, PersonCell } from "./EntityCell";

describe("initialsOf", () => {
  it("takes the first letters of the first two words", () => {
    expect(initialsOf("Каримов Сардор Алиевич")).toBe("КС");
    expect(initialsOf("Dilnoza")).toBe("D");
    expect(initialsOf("  ")).toBe("?");
  });

  it("drops the legal form and quotes for a company", () => {
    expect(initialsOf("ООО «Рельс Сервис»", true)).toBe("РС");
    expect(initialsOf('"Temir Yo\'l" MCHJ', true)).toBe("TY");
  });
});

describe("PersonCell", () => {
  it("shows initials without a photo and the caption under the name", () => {
    const { container } = render(<PersonCell name="Каримов Сардор" caption="Снабженец" />);
    expect(container.querySelector(".pf-entity__pic")).toHaveTextContent("КС");
    expect(container.querySelector(".pf-entity__pic")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByText("Снабженец")).toHaveClass("pf-entity__caption");
  });

  it("shows the photo and falls back to initials when it fails", () => {
    const { container } = render(<PersonCell name="Каримов Сардор" photoUrl="/p.jpg" />);
    const img = container.querySelector("img");
    expect(img).toHaveAttribute("alt", "");
    fireEvent.error(img as HTMLImageElement);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector(".pf-entity__pic")).toHaveTextContent("КС");
  });

  it("links the name only when an address is given", () => {
    render(
      <MemoryRouter>
        <PersonCell name="Каримов Сардор" to="/people/7" />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "Каримов Сардор" })).toHaveAttribute(
      "href",
      "/people/7",
    );
  });
});

describe("CompanyCell", () => {
  it("shows a square with letters and the INN announced with its label", () => {
    const { container } = render(<CompanyCell name="ООО «Рельс Сервис»" inn="300000777" />);
    const pic = container.querySelector(".pf-entity__pic");
    expect(pic).toHaveClass("pf-entity__pic--square");
    expect(pic).toHaveTextContent("РС");
    expect(container).toHaveTextContent("ООО «Рельс Сервис»ИНН: 300000777");
    expect(screen.getByText("300000777")).toHaveClass("pf-code");
  });
});

describe("ItemCell", () => {
  it("shows a type icon without a photo and our article", () => {
    const { container } = render(<ItemCell name="Монтаж стрелки" sku="SV-01" kind="service" />);
    expect(container.querySelector(".pf-entity__pic svg")).not.toBeNull();
    expect(container).toHaveTextContent("Монтаж стрелкиАртикул: SV-01");
  });

  it("shows the thumbnail when there is a photo", () => {
    const { container } = render(<ItemCell name="Рельс Р65" photoUrl="/r65.jpg" />);
    expect(container.querySelector("img")).toHaveAttribute("src", "/r65.jpg");
  });
});
