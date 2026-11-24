import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { LetterCard } from "../../../shared/api/generated/model";
import { readLetters, writeLetters } from "../../../mocks/fixtures/letters";
import { renderAt, setupLetterTests, signIn } from "../../../test/lettersKit";
import { server } from "../../../test/server";

setupLetterTests();

const person = (id: string, name: string, initials: string) => ({ id, name, initials });
const director = person("u-demo-director", "Демо Директоров", "ДД");
const executor = person("u-demo-universal", "Демо Широков", "ДШ");
const accountant = person("u-demo-accountant", "Демо Бухгалтеров", "ДБ");

/** Человек в карточке — общая ячейка (ЕД-3): круг с фото или инициалами и имя, без должности. */
function entityOf(root: HTMLElement, name: string): HTMLElement {
  const text = within(root).getAllByText(name)[0];
  const entity = text?.closest<HTMLElement>(".pf-entity");
  if (!entity) throw new Error(`«${name}» — не ячейка человека`);
  return entity;
}

describe("ЕД-3: люди в резолюции, поручениях и ознакомлении", () => {
  it("исполнитель, автор резолюции, переносы и ознакомление — общая ячейка человека без должности", async () => {
    const patch: Partial<LetterCard> = {
      status: "in_execution",
      on_control: true,
      office_resolution: {
        kind: "execute",
        text: "Подготовить пояснения",
        due: "2030-01-10",
        responsible: executor,
        co_executors: [accountant],
        acquaint: [],
        decided_by: director,
        decided_at: "2026-11-01T05:00:00Z",
      },
      acquaintances: [{ person: accountant, acknowledged_at: null }],
      instructions: [
        {
          id: "i-1",
          kind: "execute",
          role: "responsible",
          person: executor,
          due: "2030-01-10",
          text: "Подготовить пояснения",
          status: "in_work",
          overdue: false,
          report: null,
          files: [],
          outgoing: null,
          handed_to: null,
          executed_at: null,
          extensions: [
            {
              id: "e-1",
              old_due: "2030-01-10",
              new_due: "2030-01-17",
              reason: "Ждём выписку банка",
              status: "approved",
              requested_by: executor,
              requested_at: "2026-11-02T05:00:00Z",
              decided_by: director,
              decided_at: "2026-11-03T05:00:00Z",
              comment: null,
            },
          ],
        },
      ],
    };
    writeLetters(readLetters().map((l) => (l.number === "ВХ-108/26" ? { ...l, ...patch } : l)));
    let positionsRequested = false;
    server.events.on("response:mocked", ({ request }) => {
      if (new URL(request.url).pathname.endsWith("/staff")) positionsRequested = true;
    });
    signIn("director@demo.example");
    renderAt("/eds/inbox/%D0%92%D0%A5-108%2F26?panel=open&tab=resolution");

    const card = (await screen.findByRole("heading", { level: 2, name: "Поручения" })).closest(
      ".ant-card",
    ) as HTMLElement;
    const instruction = within(card).getByText("ответственный").closest("li") as HTMLElement;
    // исполнитель — ячейка человека, роль в документе второй строкой
    expect(entityOf(instruction, "Демо Широков")).toHaveTextContent("ДШ");
    expect(entityOf(instruction, "Демо Широков")).toHaveTextContent("ответственный");
    // справочник сотрудников загрузился (иначе проверка «без должностей» ничего не доказывает)
    await waitFor(() => {
      expect(positionsRequested).toBe(true);
    });
    await new Promise((resolve) => setTimeout(resolve, 100));
    // перенос срока: кто запросил и кто решил — те же ячейки
    const history = within(instruction).getByRole("list");
    expect(history.querySelectorAll(".pf-entity")).toHaveLength(2);
    // ознакомление
    const acq = within(card).getByRole("heading", { level: 3 }).nextElementSibling as HTMLElement;
    expect(entityOf(acq, "Демо Бухгалтеров")).toHaveTextContent("ДБ");
    // резолюция: ответственный, соисполнитель и автор — ячейки; должностей («Директор») нет
    const decision = screen
      .getByRole("heading", { level: 2, name: /Резолюция/ })
      .closest(".ant-card") as HTMLElement;
    expect(decision.querySelectorAll(".pf-entity").length).toBeGreaterThanOrEqual(3);
    expect(entityOf(decision, "Демо Директоров")).toHaveTextContent("ДД");
    // вторая строка ячейки — только роль в документе, никогда должность из справочника
    const captions = [
      ...card.querySelectorAll(".pf-entity__caption"),
      ...decision.querySelectorAll(".pf-entity__caption"),
    ].map((el) => el.textContent);
    for (const position of ["Директор", "Менеджер-универсал", "Бухгалтер"]) {
      expect(captions).not.toContain(position);
    }
  });
});
