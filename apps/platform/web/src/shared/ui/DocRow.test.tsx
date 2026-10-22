import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderUi } from "../../test/renderUi";
import { DocList, DocRow } from "./DocRow";
import { StatusTag } from "./StatusTag";

describe("DocRow и DocList", () => {
  it("номер и тип · тег статуса и история · действие", () => {
    renderUi(
      <DocList title="Документы проекта" extra={<button type="button">+ Добавить документ</button>}>
        <DocRow
          number="СЧ-2026/142"
          type="Счёт на предоплату 50 %"
          status={<StatusTag kind="invoice" status="proof_received" />}
          note="выставлен 27.10"
          action={<button type="button">Подтвердить оплату</button>}
        />
        <DocRow
          number="АКТ-2026/—"
          type="Акт"
          status={<StatusTag tone="default">После ПНР</StatusTag>}
        />
      </DocList>,
    );
    const section = screen.getByRole("region", { name: "Документы проекта" });
    const rows = within(section).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("СЧ-2026/142");
    expect(rows[0]).toHaveTextContent("Счёт на предоплату 50 %");
    expect(rows[0]).toHaveTextContent("Платёжка получена");
    expect(rows[0]).toHaveTextContent("выставлен 27.10");
    expect(
      within(rows[0] as HTMLElement).getByRole("button", { name: "Подтвердить оплату" }),
    ).toBeVisible();
    expect(within(rows[1] as HTMLElement).queryByRole("button")).toBeNull();
  });

  it("номер не переводится и не рвётся; с base — ссылка на карточку в кодировке URL", () => {
    renderUi(
      <DocList title="Документы">
        <DocRow
          number="ПР-2026-104"
          type="Проект"
          status={<StatusTag tone="blue">Идёт</StatusTag>}
          base="/eds/projects/"
        />
      </DocList>,
    );
    const link = screen.getByRole("link", { name: "ПР-2026-104" });
    expect(link).toHaveAttribute("href", "/eds/projects/%D0%9F%D0%A0-2026-104");
    expect(screen.getByText("ПР-2026-104")).toHaveAttribute("translate", "no");
  });

  it("уровень заголовка карточки", () => {
    renderUi(
      <DocList title="Документы" headingLevel={3}>
        {null}
      </DocList>,
    );
    expect(screen.getByRole("heading", { level: 3, name: "Документы" })).toBeVisible();
  });
});
