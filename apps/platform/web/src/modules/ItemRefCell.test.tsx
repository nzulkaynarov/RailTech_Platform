import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AuthContext } from "../app/auth/useAuth";
import { buildMe, readSession } from "../mocks/mockSession";
import type { ItemRef } from "../shared/api/generated/model";
import { signIn } from "../test/edsKit";
import { renderUi } from "../test/renderUi";
import { ItemRefCell } from "./ItemRefCell";

const RAIL: ItemRef = {
  id: "31",
  name: "Рельс Р65",
  sku: "RT-00031",
  kind: "goods",
  thumbnail: "/api/v1/erp/catalog/items/31/thumbnail?v=5",
};

function renderAs(email: string, ui: React.ReactElement) {
  signIn(email);
  const session = readSession();
  if (!session) throw new Error("нет сессии мока");
  const me = buildMe(session);
  if (!me) throw new Error("нет профиля мока");
  return renderUi(
    <AuthContext.Provider value={{ me, mustChangePassword: false }}>{ui}</AuthContext.Provider>,
  );
}

describe("ItemRefCell (ЕД-4)", () => {
  it("позиция строки: миниатюра, слова строки, наш артикул; название ведёт в карточку каталога", () => {
    const { container } = renderAs(
      "manager@demo.example",
      <ItemRefCell item={RAIL} name="рельсы р65 б/у" />,
    );
    expect(screen.getByRole("link", { name: "рельсы р65 б/у" })).toHaveAttribute(
      "href",
      "/erp/catalog?item=31&panel=open",
    );
    expect(screen.getByText("RT-00031")).toBeVisible();
    expect(container.querySelector("img")).toHaveAttribute("src", RAIL.thumbnail);
  });

  it("без раздела каталога — текст; без карточки — значок типа и текст", () => {
    renderAs("registrar@demo.example", <ItemRefCell item={RAIL} />);
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText("Рельс Р65")).toBeVisible();

    const { container } = renderAs(
      "manager@demo.example",
      <ItemRefCell item={null} name="Шефмонтаж" kind="service" />,
    );
    expect(screen.getByText("Шефмонтаж")).toBeVisible();
    expect(container.querySelector("img")).toBeNull();
  });
});
