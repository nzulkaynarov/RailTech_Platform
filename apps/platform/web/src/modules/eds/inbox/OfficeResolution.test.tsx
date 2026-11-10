import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { http } from "msw";
import { describe, expect, it } from "vitest";

import type { LetterCard, OfficeResolutionIn } from "../../../shared/api/generated/model";
import { findLetter, readLetters, writeLetters } from "../../../mocks/fixtures/letters";
import { chooseOption } from "../../../test/fields";
import { renderAt, setupLetterTests, signIn } from "../../../test/lettersKit";
import { server } from "../../../test/server";

setupLetterTests();

const TAX = "/eds/inbox/%D0%92%D0%A5-108%2F26?panel=open&tab=resolution";
const person = (id: string, name: string) => ({ id, name, initials: "ДД" });

function patchLetter(number: string, patch: Partial<LetterCard>): void {
  writeLetters(readLetters().map((l) => (l.number === number ? { ...l, ...patch } : l)));
}

async function directorForm(path = TAX) {
  signIn("director@demo.example");
  renderAt(path);
  return screen.findByRole("form", { name: "Резолюция директора" }, { timeout: 3000 });
}

describe("Резолюция делопроизводства (P8b, SPEC-v3 §3.2a п. 2)", () => {
  it("письмо по заявке клиента — по-прежнему «расчёт по зонам»", async () => {
    signIn("director@demo.example");
    renderAt("/eds/inbox/%D0%92%D0%A5-104%2F26?panel=open&tab=resolution");
    expect(
      await screen.findByRole(
        "button",
        { name: /Утвердить резолюцию/ },
        {
          timeout: 3000,
        },
      ),
    ).toBeVisible();
    expect(screen.queryByRole("radio", { name: /К исполнению/ })).toBeNull();
  });

  it("«К исполнению»: ответственный — любой сотрудник, срок — подсказка EDS; письмо «На исполнении» и на контроле", async () => {
    let body = null as OfficeResolutionIn | null;
    server.use(
      http.post("*/eds/letters/:id/office-resolution", async ({ request }) => {
        body = (await request.clone().json()) as OfficeResolutionIn;
        return undefined;
      }),
    );
    const form = await directorForm();
    expect(within(form).getByLabelText("Текст резолюции")).toHaveValue(
      "Прошу исполнить и доложить в срок.",
    );
    expect(within(form).getByLabelText("Срок исполнения")).not.toHaveValue("");
    expect(within(form).getByText(/Подсказка — /)).toBeVisible();

    fireEvent.click(within(form).getByRole("button", { name: "Наложить резолюцию" }));
    expect(await within(form).findByText("Выберите ответственного.")).toBeVisible();

    await chooseOption(within(form).getByLabelText("Ответственный"), "Демо Широков");
    fireEvent.click(within(form).getByRole("button", { name: "Наложить резолюцию" }));

    expect(
      await screen.findByText("Резолюция наложена: поручение ушло исполнителям"),
    ).toBeVisible();
    await waitFor(() => {
      expect(body).not.toBeNull();
    });
    expect(body).toMatchObject({
      kind: "execute",
      responsible_id: "u-demo-universal",
      text: "Прошу исполнить и доложить в срок.",
      co_executor_ids: [],
      acquaint_ids: [],
    });
    await waitFor(() => {
      expect(findLetter("ВХ-108/26")?.status).toBe("in_execution");
    });
    const card = await screen.findByText("Поручения");
    expect(card).toBeVisible();
    expect(screen.getAllByText("На контроле").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Демо Широков").length).toBeGreaterThan(0);
  });

  it("«Для сведения»: без ответственного и срока; письмо «Принято к сведению», «Ознакомить» получают задачу", async () => {
    const form = await directorForm();
    fireEvent.click(within(form).getByRole("radio", { name: /Для сведения/ }));
    expect(within(form).queryByLabelText("Ответственный")).toBeNull();
    expect(within(form).queryByLabelText("Срок исполнения")).toBeNull();
    expect(within(form).getByLabelText("Текст резолюции")).toHaveValue("Принять к сведению.");
    await chooseOption(within(form).getByLabelText("Ознакомить"), "Демо Бухгалтеров");
    fireEvent.click(within(form).getByRole("button", { name: "Наложить резолюцию" }));

    expect(await screen.findByText("Письмо принято к сведению")).toBeVisible();
    await waitFor(() => {
      expect(findLetter("ВХ-108/26")?.status).toBe("noted");
    });
    const acquaint = findLetter("ВХ-108/26")?.acquaintances ?? [];
    expect(acquaint.map((a) => [a.person.id, a.acknowledged_at])).toEqual([
      ["u-demo-accountant", null],
    ]);
  });

  it("делопроизводитель сохраняет проект; директор утверждает его одним нажатием", async () => {
    signIn("registrar@demo.example");
    renderAt(TAX);
    const draft = await screen.findByRole("form", { name: "Проект резолюции" }, { timeout: 3000 });
    fireEvent.click(within(draft).getByRole("radio", { name: /Подготовить ответ/ }));
    await chooseOption(within(draft).getByLabelText("Ответственный"), "Демо Широков");
    fireEvent.click(within(draft).getByRole("button", { name: "Сохранить проект" }));
    expect(await screen.findByText("Проект резолюции сохранён")).toBeVisible();
    await waitFor(() => {
      expect(findLetter("ВХ-108/26")?.resolution_draft?.kind).toBe("reply");
    });
    cleanup();

    const form = await directorForm();
    expect(within(form).getByText(/Проект подготовил\(а\) Демо Канцелярова/)).toBeVisible();
    expect(within(form).getByRole("radio", { name: /Подготовить ответ/ })).toBeChecked();
    fireEvent.click(within(form).getByRole("button", { name: "Утвердить проект" }));
    await waitFor(() => {
      expect(findLetter("ВХ-108/26")?.status).toBe("in_execution");
    });
    const first = findLetter("ВХ-108/26")?.instructions?.[0];
    expect([first?.kind, first?.person.id]).toEqual(["reply", "u-demo-universal"]);
  });

  it("автор резолюции решает перенос: «Отклонить» — срок прежний, история в карточке", async () => {
    const director = person("u-demo-director", "Демо Директоров");
    const executor = person("u-demo-universal", "Демо Широков");
    patchLetter("ВХ-108/26", {
      status: "in_execution",
      urgent: false,
      on_control: true,
      office_resolution: {
        kind: "execute",
        text: "Подготовить пояснения",
        due: "2030-01-10",
        responsible: executor,
        co_executors: [],
        acquaint: [],
        decided_by: director,
        decided_at: "2026-11-01T05:00:00Z",
      },
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
          executed_at: null,
          extensions: [
            {
              id: "e-1",
              old_due: "2030-01-10",
              new_due: "2030-01-17",
              reason: "Ждём выписку банка",
              status: "pending",
              requested_by: executor,
              requested_at: "2026-11-02T05:00:00Z",
              decided_by: null,
              decided_at: null,
              comment: null,
            },
          ],
        },
      ],
    });
    signIn("director@demo.example");
    renderAt("/eds/inbox/%D0%92%D0%A5-108%2F26");
    const decide = await screen.findByRole("region", { name: "Перенос срока: нужно ваше решение" });
    expect(
      within(decide).getByText(/Демо Широков просит перенести срок с 10\.01\.2030/),
    ).toBeVisible();
    fireEvent.click(within(decide).getByRole("button", { name: "Отклонить перенос" }));
    expect(await screen.findByText("Перенос отклонён: срок прежний")).toBeVisible();
    await waitFor(() => {
      expect(findLetter("ВХ-108/26")?.instructions?.[0]?.extensions[0]?.status).toBe("rejected");
    });
    expect(findLetter("ВХ-108/26")?.instructions?.[0]?.due).toBe("2030-01-10");
    expect(
      await screen.findByText(/10\.01\.2030 → 17\.01\.2030: Ждём выписку банка/),
    ).toBeVisible();
  });
});

describe("Срочное письмо: перенос можно запросить, одобрить нельзя (Росархив 5.14)", () => {
  it("автор резолюции видит «Одобрить перенос» недоступной с пояснением; «Отклонить» — доступна", async () => {
    const director = person("u-demo-director", "Демо Директоров");
    const executor = person("u-demo-universal", "Демо Широков");
    patchLetter("ВХ-108/26", {
      status: "in_execution",
      urgent: true,
      on_control: true,
      office_resolution: {
        kind: "execute",
        text: "Ответить",
        due: "2030-01-10",
        responsible: executor,
        co_executors: [],
        acquaint: [],
        decided_by: director,
        decided_at: "2026-11-01T05:00:00Z",
      },
      instructions: [
        {
          id: "i-3",
          kind: "execute",
          role: "responsible",
          person: executor,
          due: "2030-01-10",
          text: "Ответить",
          status: "in_work",
          overdue: false,
          report: null,
          files: [],
          outgoing: null,
          executed_at: null,
          extensions: [
            {
              id: "e-3",
              old_due: "2030-01-10",
              new_due: "2030-01-17",
              reason: "Не успеваем",
              status: "pending",
              requested_by: executor,
              requested_at: "2026-11-02T05:00:00Z",
              decided_by: null,
              decided_at: null,
              comment: null,
            },
          ],
        },
      ],
    });
    signIn("director@demo.example");
    renderAt("/eds/inbox/%D0%92%D0%A5-108%2F26");
    const decide = await screen.findByRole("region", { name: "Перенос срока: нужно ваше решение" });
    const approve = within(decide).getByRole("button", { name: "Одобрить перенос" });
    expect(approve).toBeDisabled();
    expect(approve).toHaveAccessibleDescription(/срок не продлевается/);
    expect(within(decide).getByRole("button", { name: "Отклонить перенос" })).toBeEnabled();
  });
});

describe("Журнал «Входящие письма»: фильтры и колонки (P8b, §3.2a п. 6)", () => {
  it("«На контроле», «Просрочено», «Исполнено»; колонки «Исполнитель» и «Срок» (просрочка словом)", async () => {
    const executor = person("u-demo-universal", "Демо Широков");
    patchLetter("ВХ-108/26", {
      status: "in_execution",
      on_control: true,
      instructions: [
        {
          id: "i-2",
          kind: "execute",
          role: "responsible",
          person: executor,
          due: "2020-01-10",
          text: "Ответить",
          status: "in_work",
          overdue: true,
          report: null,
          files: [],
          outgoing: null,
          executed_at: null,
          extensions: [],
        },
      ],
    });
    signIn("director@demo.example");
    renderAt("/eds/inbox");
    const filter = await screen.findByRole("radiogroup", { name: "Статус письма" });
    fireEvent.click(within(filter).getByText("На контроле"));
    const link = await screen.findByRole("link", {
      name: "Показать письмо ВХ-108/26 в боковом окне",
    });
    const tr = link.closest("tr") as HTMLElement;
    expect(within(tr).getByText("Демо Широков")).toBeVisible();
    expect(within(tr).getByText("10.01.2020, просрочено")).toBeVisible();
    expect(screen.getAllByRole("row")).toHaveLength(2);

    fireEvent.click(within(filter).getByText("Просрочено"));
    expect(
      await screen.findByRole("link", { name: "Показать письмо ВХ-108/26 в боковом окне" }),
    ).toBeVisible();

    fireEvent.click(within(filter).getByText("Исполнено"));
    expect(await screen.findByText("Писем с таким статусом нет")).toBeVisible();
  });
});
