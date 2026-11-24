import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { panelEl, renderAt, setupCalcTests, signIn } from "../../../test/calcKit";
import { readyHintKey } from "./api";

setupCalcTests();

const NUMBER = "ЗВ-2026-097";
const PATH = `/erp/calc/${encodeURIComponent(NUMBER)}`;
const READY = "Расчёт готов";

async function openCalc(email: string) {
  signIn(email);
  const view = renderAt(PATH);
  expect(
    await screen.findByRole("heading", { level: 1, name: `Расчёт по заявке ${NUMBER}` }),
  ).toBeVisible();
  return view;
}

function lineRow(name: string): HTMLElement {
  const table = screen.getByRole("table", { name: `Строки расчёта по заявке ${NUMBER}` });
  const cell = within(table).getAllByText(name)[0];
  const tr = cell?.closest("tr");
  if (!tr) throw new Error(`нет строки ${name}`);
  return tr;
}

describe("Расчёт · Заявки в расчёте", () => {
  it("таблица: ЗВ-номер, клиент, стадия, срок, три индикатора виз, ответственный, «Открыть расчёт»", async () => {
    signIn("supply@demo.example");
    renderAt("/erp/requests");
    expect(await screen.findByRole("heading", { level: 1, name: "Заявки" })).toBeVisible();
    const link = await screen.findByRole("link", { name: `Открыть расчёт по заявке ${NUMBER}` });
    expect(link).toHaveAttribute("href", PATH);
    const row = link.closest("tr");
    if (!row) throw new Error("нет строки");
    expect(within(row).getByText("АО «Пример Логистик»")).toBeVisible();
    expect(within(row).getByText("Расчёт")).toBeVisible();
    expect(within(row).getByText("Склад: ждёт визы")).toBeInTheDocument();
    expect(within(row).getByText("Снабжение: ждёт визы")).toBeInTheDocument();
    expect(within(row).getByText("Услуги: ждёт визы")).toBeInTheDocument();
    expect(within(row).getByText("Демо Менеджеров")).toBeVisible();
  });

  it("«Мои расчёты» без заданий — пустое состояние словами и с действием", async () => {
    signIn("accountant@demo.example");
    renderAt("/erp/calc");
    expect(await screen.findByText("Пока пусто.")).toBeVisible();
  });

  it("клик по строке — «Задание» в боковом окне без перехода", async () => {
    signIn("supply@demo.example");
    renderAt("/erp/requests");
    const select = await screen.findByRole("link", {
      name: `Показать задание по заявке ${NUMBER} в боковом окне`,
    });
    fireEvent.click(select);
    const panel = await panelEl();
    expect(
      await within(panel).findByText(/Посчитать переводы со склада и под заказ/),
    ).toBeVisible();
    expect(within(panel).getByRole("link", { name: "Открыть расчёт" })).toHaveAttribute(
      "href",
      PATH,
    );
  });
});

describe("Расчёт по заявке", () => {
  it("снабженец: себестоимость видна, подтверждает только товары, «Расчёт готов» неактивна с подписью почему", async () => {
    await openCalc("supply@demo.example");
    expect(
      screen.getByText(/АО «Пример Логистик» · письмо ВХ-097\/26 · срок расчёта 30\.10\.2026/),
    ).toBeVisible();
    expect(screen.getByText(/маржа не ниже 15.00 %/)).toBeVisible();
    const rail = lineRow("Перевод стрелочный Р65 марки 1/11");
    expect(within(rail).getByText("Товар под заказ")).toBeVisible();
    expect(within(rail).getByText("На складе · 1")).toBeVisible();
    expect(within(rail).getByText(/ООО «Вымышленная Сталь» · 45 дн\./)).toBeVisible();
    expect(
      within(rail).getByLabelText("Закупка за единицу для «Перевод стрелочный Р65 марки 1/11»"),
    ).toBeEnabled();
    // Валюта закупки строки видна рядом с суммой (прод, ЗВ-2026-002: сумма в сумах у строки в USD).
    expect(
      within(rail).getByRole("combobox", {
        name: "Валюта закупки для «Перевод стрелочный Р65 марки 1/11»",
      }),
    ).toBeEnabled();
    expect(within(rail).getByText("сум")).toBeVisible();
    expect(
      within(rail).getByLabelText<HTMLInputElement>("Наценка, %: Перевод стрелочный Р65 марки 1/11")
        .value,
    ).toMatch(/^15([.,]0+)?$/);
    expect(
      within(rail).getByRole("button", {
        name: "Подтвердить строку «Перевод стрелочный Р65 марки 1/11»",
      }),
    ).toBeVisible();

    const mounting = lineRow("Монтаж и пусконаладка стрелочного перевода");
    expect(within(mounting).getByText("Услуги · ждёт")).toBeVisible();
    expect(
      within(mounting).getByLabelText(
        "Ставка бригады для «Монтаж и пусконаладка стрелочного перевода»",
      ),
    ).toBeDisabled();

    const ready = screen.getByRole("button", { name: READY });
    expect(ready).toBeDisabled();
    expect(screen.getByText(/без визы 3\. Ждут визы: Склад, Снабжение, Услуги\./)).toBeVisible();
    expect(screen.getByText(/без НДС/)).toBeVisible();
  });

  it("гл. инженер не видит закупку и наценку, правит ставку бригады и дни у услуги", async () => {
    await openCalc("engineer@demo.example");
    const rail = lineRow("Перевод стрелочный Р65 марки 1/11");
    expect(within(rail).queryByLabelText(/Закупка за единицу/)).toBeNull();
    expect(within(rail).getByText("Снабжение · ждёт")).toBeVisible();
    expect(screen.queryByText("90 000 000")).toBeNull();
    const mounting = lineRow("Монтаж и пусконаладка стрелочного перевода");
    expect(
      within(mounting).getByLabelText(
        "Ставка бригады для «Монтаж и пусконаладка стрелочного перевода»",
      ),
    ).toBeEnabled();
    expect(
      within(mounting).getByRole("button", { name: /Подтвердить строку «Монтаж/ }),
    ).toBeVisible();
  });

  it("бухгалтер — только чтение: цены клиенту и итог, без себестоимости, ставок бригады и цен партнёра", async () => {
    await openCalc("accountant@demo.example");
    expect(screen.queryByRole("button", { name: /Подтвердить строку/ })).toBeNull();
    expect(screen.queryByRole("button", { name: READY })).toBeNull();
    const totals = screen.getByText("Итого").closest("tr");
    if (!totals) throw new Error("нет итогов");
    expect(within(totals).getByText("275 300 000")).toBeVisible();
    expect(screen.queryByText("239 000 000")).toBeNull();
    expect(screen.queryByText(/1 500 000/)).toBeNull();
    expect(screen.queryByText(/Цена партнёра/)).toBeNull();
    expect(screen.queryByLabelText(/Ставка бригады/)).toBeNull();
  });

  it("подсказка «Расчёт готов» для закрытого расчёта называет состояние КП", () => {
    const quote = {
      number: "КП-1",
      version: 1,
      director_comment: null,
      rejected_by: null,
      reject_reason: null,
      can_revise: false,
      vat_rate: "12.00",
    };
    const ready = { allowed: false, blocker: "not_draft", missing: 0 } as const;
    expect(readyHintKey({ ready, quote: { ...quote, state: "approved" } })).toBe("approved");
    expect(
      readyHintKey({ ready, quote: { ...quote, state: "rejected", rejected_by: "director" } }),
    ).toBe("rejected");
    expect(
      readyHintKey({ ready, quote: { ...quote, state: "rejected", rejected_by: "client" } }),
    ).toBe("rejected_client");
    expect(readyHintKey({ ready, quote: { ...quote, state: "at_director" } })).toBe("at_director");
    expect(readyHintKey({ ready: { ...ready, blocker: "visas_missing" }, quote: null })).toBe(
      "visas_missing",
    );
  });

  it("снабженец визирует товары, гл. инженер — услугу; после второй визы «Расчёт готов» отправляет КП директору", async () => {
    await openCalc("supply@demo.example");
    fireEvent.click(
      screen.getByRole("button", {
        name: "Подтвердить строку «Перевод стрелочный Р65 марки 1/11»",
      }),
    );
    await waitFor(() => {
      expect(
        within(lineRow("Перевод стрелочный Р65 марки 1/11")).getByText(
          "Снабжение ✓ Демо Снабженцев",
        ),
      ).toBeVisible();
    });
    fireEvent.click(screen.getByRole("button", { name: /Подтвердить строку «Привод/ }));
    await waitFor(() => {
      expect(screen.getByText(/без визы 1\. Ждут визы: Услуги\./)).toBeVisible();
    });
  });
});

describe("Расчёт · файлы заявки клиента (СЦ-10)", () => {
  it("в задании (боковое окно) — файл клиента со ссылкой на скачивание", async () => {
    signIn("supply@demo.example");
    renderAt("/erp/requests");
    fireEvent.click(
      await screen.findByRole("link", {
        name: `Показать задание по заявке ${NUMBER} в боковом окне`,
      }),
    );
    const panel = await panelEl();
    const link = await within(panel).findByRole("link", { name: "Скачать файл spec.pdf" });
    expect(link).toHaveAttribute(
      "href",
      `/api/v1/erp/calc/${encodeURIComponent(NUMBER)}/request-files/7`,
    );
    expect(link).toHaveAttribute("download");
    expect(within(panel).getByRole("heading", { name: "Файлы заявки" })).toBeVisible();
  });

  it("до начала расчёта — файл под текстом заявки", async () => {
    signIn("supply@demo.example");
    const number = "ЗВ-2026-103";
    renderAt(`/erp/calc/${encodeURIComponent(number)}`);
    expect(await screen.findByRole("heading", { name: "Расчёт ещё не начат" })).toBeVisible();
    const files = screen.getByRole("list", { name: "Файлы заявки" });
    expect(
      within(files).getByRole("link", { name: "Скачать файл Ведомость брусьев.xlsx" }),
    ).toHaveAttribute("href", `/api/v1/erp/calc/${encodeURIComponent(number)}/request-files/8`);
  });
});
