import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderAt, setupProjectTests, signIn } from "../../../test/projectsKit";

setupProjectTests();

const PR97 = `/eds/projects/${encodeURIComponent("ПР-2026-097")}`;

async function execution() {
  const heading = await screen.findByRole("heading", { name: "Исполнение" });
  return heading.closest(".ant-card") as HTMLElement;
}

async function openDialog(card: HTMLElement, button: string, title: string) {
  await within(card).findByRole("button", { name: button });
  fireEvent.click(within(card).getByRole("button", { name: button }));
  return screen.findByRole("form", { name: title });
}

/** L0-1: «Отправлено, в пути» и «Доставлено» в карточке проекта — у того, кому положен склад. */
describe("Проект: отметки доставки", () => {
  it("снабженец отмечает «в пути», затем «доставлено» с накладной и файлом", async () => {
    signIn("supply@demo.example");
    renderAt(PR97);
    const card = await execution();
    expect(card).toHaveTextContent("Отгружено");
    expect(within(card).getByRole("button", { name: "Отправлено, в пути" })).toBeVisible();

    const transit = await openDialog(card, "Отправлено, в пути", "Отправлено клиенту, в пути");
    expect(within(transit).queryByLabelText("Подтверждение доставки")).toBeNull(); // файл — только к «доставлено»
    expect(transit).toHaveTextContent("Клиент увидит в кабинете, что поставка в пути");
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(card).toHaveTextContent("В пути");
    });
    expect(within(card).queryByRole("button", { name: "Отправлено, в пути" })).toBeNull();

    const delivered = await openDialog(card, "Доставлено", "Доставлено клиенту");
    fireEvent.change(within(delivered).getByLabelText("№ накладной перевозчика или трек"), {
      target: { value: "CMR-0042" },
    });
    const file = new File(["%PDF-1.4 pod"], "pod.pdf", { type: "application/pdf" });
    fireEvent.change(within(delivered).getByLabelText("Подтверждение доставки"), {
      target: { files: [file] },
    });
    expect(delivered).toHaveTextContent("сможет принять поставку или написать замечания");
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() => {
      expect(within(card).getByRole("link", { name: "pod.pdf" })).toBeVisible();
    });
    expect(card).toHaveTextContent("CMR-0042");
    expect(within(card).queryByRole("button", { name: "Доставлено" })).toBeNull();
    const lines = within(card).getByRole("region", { name: "Строки поставки" });
    expect(lines).toHaveTextContent("Доставлено");
    expect(
      screen.getByRole("heading", { name: "Журнал документов" }).closest(".ant-card"),
    ).toHaveTextContent("Доставлено клиенту");
  });

  it("менеджер видит исполнение без отметок", async () => {
    signIn("manager@demo.example");
    renderAt(PR97);
    const card = await execution();
    expect(card).toHaveTextContent("Отгружено");
    expect(within(card).queryByRole("button", { name: "Доставлено" })).toBeNull();
    expect(within(card).queryByRole("button", { name: "Отправлено, в пути" })).toBeNull();
  });
});
