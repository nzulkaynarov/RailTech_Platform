import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderAt, setupApprovalTests, signIn } from "../../../test/approvalsKit";
import { chooseOption } from "../../../test/fields";

// A1 волны 18a «Отметить за контрагента»: отправленное КП ждёт решения клиента; клиент ответил письмом — менеджер
// записывает «Клиент принял» / «Клиент отклонил» с каналом, лицом, датой, комментарием и обязательным подтверждением.
setupApprovalTests(1440);

const SENT = `/eds/drafts/${encodeURIComponent("КП-2026/113")}`;
const letter = () => new File(["%PDF-1.4 letter"], "letter.pdf", { type: "application/pdf" });

async function openDialog(button: "Клиент принял" | "Клиент отклонил") {
  const card = (await screen.findByRole("heading", { name: "Решение клиента" })).closest(
    ".ant-card",
  ) as HTMLElement;
  expect(within(card).getByText("Ждёт решения клиента.")).toBeVisible();
  fireEvent.click(within(card).getByRole("button", { name: button }));
  const dialog = await screen.findByRole("dialog", {
    name: button === "Клиент принял" ? "Клиент принял КП" : "Клиент отклонил КП",
  });
  return { card, dialog };
}

async function fill(dialog: HTMLElement, comment: string, withFile = true) {
  await chooseOption(within(dialog).getByLabelText("Как клиент сообщил"), "почта");
  fireEvent.change(within(dialog).getByLabelText("Кто со стороны клиента"), {
    target: { value: "Каримов А., снабженец" },
  });
  fireEvent.change(within(dialog).getByRole("textbox", { name: /Что ответил клиент|Причина/ }), {
    target: { value: comment },
  });
  if (withFile) {
    fireEvent.change(within(dialog).getByLabelText("Подтверждение клиента"), {
      target: { files: [letter()] },
    });
    await within(dialog).findByText("letter.pdf");
  }
}

describe("Решение клиента по отправленному КП", () => {
  it("менеджер записывает «Клиент принял» — КП принято, значок «Отмечено сотрудником» и файл", async () => {
    signIn("manager@demo.example");
    renderAt(SENT);
    const { card, dialog } = await openDialog("Клиент принял");
    expect(within(dialog).getByText(/как при принятии в кабинете/)).toBeInTheDocument();

    await fill(dialog, "Согласны, ждём договор");
    fireEvent.click(within(dialog).getByRole("button", { name: "Записать" }));

    expect(await within(card).findByText(/^Клиент принял КП\./)).toBeVisible();
    expect(within(card).getByText("Отмечено сотрудником")).toBeVisible();
    expect(within(card).getByText(/почта · подтвердил: Каримов А., снабженец/)).toBeVisible();
    expect(within(card).getByRole("link", { name: "Подтверждение: letter.pdf" })).toBeVisible();
    expect(within(card).queryByRole("button", { name: "Клиент принял" })).toBeNull();
  });

  it("без подтверждения клиента не записывается: поле говорит, что приложить", async () => {
    signIn("manager@demo.example");
    renderAt(SENT);
    const { card, dialog } = await openDialog("Клиент отклонил");
    expect(within(dialog).getByText("Причина отказа")).toBeInTheDocument();

    await fill(dialog, "Дорого", false);
    fireEvent.click(within(dialog).getByRole("button", { name: "Записать" }));

    expect(await within(dialog).findByText("Приложите подтверждение клиента")).toBeInTheDocument();
    expect(within(card).getByText("Ждёт решения клиента.")).toBeVisible();
  });

  it("«Клиент отклонил» с причиной — отказ и причина в карточке", async () => {
    signIn("manager@demo.example");
    renderAt(SENT);
    const { card, dialog } = await openDialog("Клиент отклонил");
    await fill(dialog, "Дорого, нашли дешевле");
    fireEvent.click(within(dialog).getByRole("button", { name: "Записать" }));

    expect(await within(card).findByText(/^Клиент отклонил КП\./)).toBeVisible();
    expect(within(card).getByText("Причина: Дорого, нашли дешевле")).toBeVisible();
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
  });
});
