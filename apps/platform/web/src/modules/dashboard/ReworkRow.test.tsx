import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { readEds, recordReturn, writeEds } from "../../mocks/fixtures/edsDocuments";
import { MANAGER_PERSON } from "../../mocks/fixtures/approvals";
import { renderAt, setupEdsTests, signIn } from "../../test/edsKit";

setupEdsTests();

// «Доработать» в «Моих задачах» автора (D1-6b): документ, который согласующий вернул на доработку, — строка с «Открыть» в форму
// «Продолжить» (экран D1-5). Источник мока — те же документы, что в «Моих документах»: отправил снова — строка исчезла.
const SEED_ID = "00000000-0000-4000-8000-000000000002";
const TITLE = "Доработать: СЗ-2026/028 · Командировка в Самарканд";

async function queue(email: string) {
  signIn(email);
  const view = renderAt("/dashboard/queue");
  await screen.findByRole("heading", { level: 1, name: "Мои задачи" });
  return { ...view, page: screen.getByRole("main") };
}

describe("Моя очередь · «Доработать»", () => {
  it("у автора — строка: кто вернул и комментарий; «Открыть» ведёт в форму «Продолжить»", async () => {
    const { page, router } = await queue("manager@demo.example");

    expect(await within(page).findByText(TITLE)).toBeVisible();
    expect(
      within(page).getByText(/Вернул Демо Директоров: Добавьте смету расходов\./),
    ).toBeVisible();
    const open = within(page).getByRole("link", { name: `Открыть: ${TITLE}` });
    expect(open).toHaveAttribute("href", `/eds/new?draft=${SEED_ID}`);
    // родной экран есть: «Где сделать» вместо «Открыть» не нужно
    expect(within(page).queryByRole("button", { name: `Где сделать: ${TITLE}` })).toBeNull();

    fireEvent.click(open);

    expect(
      await screen.findByRole("heading", { level: 1, name: "Создать документ" }),
    ).toBeVisible();
    await waitFor(() => {
      expect(screen.getByLabelText("Тема")).toHaveValue("Командировка в Самарканд");
    });
    expect(router.state.location.pathname + router.state.location.search).toBe(
      `/eds/new?draft=${SEED_ID}`,
    );
  });

  it("у чужого — строки нет: документ принадлежит автору", async () => {
    const { page } = await queue("supply@demo.example");

    expect(await within(page).findByText("Заданий на расчёт нет")).toBeVisible();
    expect(within(page).queryByText(TITLE)).toBeNull();
  });

  it("отправил на согласование снова — строка исчезает", async () => {
    const { page, router } = await queue("manager@demo.example");
    expect(await within(page).findByText(TITLE)).toBeVisible();

    await act(() => router.navigate(`/eds/new?draft=${SEED_ID}`));
    await waitFor(() => {
      expect(screen.getByLabelText("Тема")).toHaveValue("Командировка в Самарканд");
    });
    fireEvent.click(screen.getByRole("button", { name: "Отправить на согласование" }));
    await waitFor(() => {
      expect(readEds().documents.find((d) => d.id === SEED_ID)?.status).toBe("on_approval");
    });

    await act(() => router.navigate("/dashboard/queue"));
    const again = await screen.findByRole("heading", { level: 1, name: "Мои задачи" });
    expect(again).toBeVisible();
    await waitFor(() => {
      expect(within(screen.getByRole("main")).queryByText(TITLE)).toBeNull();
    });
  });

  it("свежий возврат другого круга попадает в очередь: последнее решение «Вернуть» и срок «нужно до»", async () => {
    const state = readEds();
    const doc = state.documents.find((d) => d.id === SEED_ID);
    if (!doc) throw new Error("нет демо-документа");
    writeEds({
      ...state,
      documents: state.documents.map((d) => (d === doc ? { ...d, due_date: "2999-01-01" } : d)),
    });
    recordReturn(
      {
        id: SEED_ID,
        number: "СЗ-2026/028",
        kind: "memo",
        subject: doc.subject,
        text: doc.text,
        amount: null,
        due_date: "2999-01-01",
        author: MANAGER_PERSON,
      },
      {
        round: 2,
        step: 1,
        decision: "return",
        comment: "Теперь укажите даты поездки.",
        by: { crm_user_id: 1, full_name: "Демо Директоров" },
        at: new Date().toISOString(),
      },
    );

    const { page } = await queue("manager@demo.example");

    expect(
      await within(page).findByText(/Вернул Демо Директоров: Теперь укажите даты поездки\./),
    ).toBeVisible();
    expect(within(page).queryByText(/Добавьте смету расходов/)).toBeNull();
  });
});
