import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  findModal,
  modalClosed,
  renderAt,
  setupCatalogTests,
  signIn,
} from "../../../test/catalogKit";
import { setViewportWidth } from "../../../test/viewport";

// jsdom не рисует canvas: настоящий просмотр PDF проверяет e2e на сборке; здесь — что ему отдали байты PDF.
vi.mock("./PdfViewer", () => ({
  default: ({ data, name }: { data: ArrayBuffer; name: string }) => (
    <div data-testid="pdf-stub">
      {name}: {new TextDecoder().decode(data.slice(0, 8))}
    </div>
  ),
}));

setupCatalogTests();

async function open(email: string, search = "") {
  signIn(email);
  const view = renderAt(`/erp/docs${search}`);
  expect(await screen.findByRole("heading", { level: 1, name: "Техдокументация" })).toBeVisible();
  return view;
}

function row(title: string): HTMLElement {
  const tr = screen.getByRole("button", { name: `Открыть файл «${title}»` }).closest("tr");
  if (!tr) throw new Error(`нет строки ${title}`);
  return tr;
}

const pdfFile = (name = "plan.pdf", size = 64) =>
  new File([new Uint8Array(size).fill(37)], name, { type: "application/pdf" });

describe("Техдокументация: список", () => {
  it("файлы с видом, привязкой к позиции и заявке (номер ЗВ/ПР), размером и автором", async () => {
    await open("manager@demo.example");

    expect(
      await screen.findByRole("button", { name: "Открыть файл «ТЗ на стрелочные переводы»" }),
    ).toBeVisible();
    const tz = row("ТЗ на стрелочные переводы");
    expect(within(tz).getByText("Техническое задание")).toBeVisible();
    expect(within(tz).getByText(/ЗВ-2026-905 · Монтаж стрелочных переводов/)).toBeVisible();
    const drawing = row("Чертёж рельса Р65");
    expect(within(drawing).getByRole("link", { name: "Рельс Р65, 25 м" })).toHaveAttribute(
      "href",
      "/erp/catalog?part=items&item=3",
    );
    expect(within(drawing).getByText(/ПР-2026-904/)).toBeVisible();
    expect(within(row("Регламент ПНР устройств СЦБ")).getByText("Регламент ПНР")).toBeVisible();
    // менеджер читает: загрузки и удаления нет
    expect(screen.queryByRole("button", { name: "Загрузить файл" })).toBeNull();
  });

  it("поиск и вид сужают список; пустой результат — словами", async () => {
    await open("manager@demo.example");
    await screen.findByRole("button", { name: /Открыть файл «Чертёж/ });

    fireEvent.change(screen.getByLabelText("Поиск по названию, файлу и позиции"), {
      target: { value: "сертификат" },
    });
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /Открыть файл «Чертёж/ })).toBeNull();
    });
    expect(await screen.findByRole("button", { name: /Открыть файл «Сертификат/ })).toBeVisible();

    fireEvent.change(screen.getByLabelText("Поиск по названию, файлу и позиции"), {
      target: { value: "нет такого" },
    });
    expect(await screen.findByText("Файлов нет")).toBeVisible();
  });

  it("ссылка из карточки позиции (?product_id=) показывает только её файлы и даёт сбросить фильтр", async () => {
    await open("manager@demo.example", "?product_id=3");

    expect(await screen.findByRole("button", { name: /Чертёж рельса/ })).toBeVisible();
    expect(screen.queryByRole("button", { name: /ТЗ на стрелочные/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Показать все файлы" }));
    expect(await screen.findByRole("button", { name: /ТЗ на стрелочные/ })).toBeVisible();
  });
});

describe("Техдокументация: просмотр", () => {
  it("PDF открывается в боковом окне: байты файла получены, про чат сказано словами, кнопки «Отправить клиенту» нет", async () => {
    await open("manager@demo.example");
    fireEvent.click(
      await screen.findByRole("button", { name: "Открыть файл «Чертёж рельса Р65»" }),
    );

    const drawer = await screen.findByRole("dialog", { name: "Чертёж рельса Р65" });
    expect(await within(drawer).findByTestId("pdf-stub")).toHaveTextContent(
      "Чертёж рельса Р65: %PDF-1.4",
    );
    expect(
      within(drawer).getByText(/Отправить клиенту в чат: появится вместе с разделом «Чаты»/),
    ).toBeVisible();
    expect(within(drawer).queryByRole("button", { name: /Отправить клиенту/ })).toBeNull();
    expect(within(drawer).getByRole("button", { name: "Скачать" })).toBeVisible();
    // читателю удаление не положено
    expect(within(drawer).queryByRole("button", { name: "Удалить файл" })).toBeNull();
  });

  it("адрес с ?doc= открывает окно сразу; закрытие убирает параметр", async () => {
    const { router } = await open("manager@demo.example", "?doc=3");
    const drawer = await screen.findByRole("dialog", { name: "Сертификат соответствия на кабель" });
    expect(await within(drawer).findByTestId("pdf-stub")).toBeVisible();
    fireEvent.click(within(drawer).getByRole("button", { name: /Закрыть|Close/ }));
    await waitFor(() => {
      expect(router.state.location.search).toBe("");
    });
  });
});

describe("Техдокументация: загрузка и удаление", () => {
  it("гл. инженер загружает PDF с привязкой к позиции: файл в списке, открывается", async () => {
    await open("engineer@demo.example", "?product_id=1");
    fireEvent.click(await screen.findByRole("button", { name: "Загрузить файл" }));

    const form = await findModal("Загрузить файл");
    const input = await within(form).findByLabelText("Файл");
    const ok = await within(form).findByRole("button", { name: "Загрузить" });
    expect(ok).toBeDisabled();
    expect(await within(form).findByText("Что произойдёт")).toBeInTheDocument();
    fireEvent.change(input, { target: { files: [pdfFile("scheme.pdf")] } });
    fireEvent.change(within(form).getByLabelText("Название"), { target: { value: "Схема шкафа" } });
    await waitFor(() => {
      expect(within(form).getByRole("button", { name: /Загрузить$/ })).toBeEnabled();
    });
    fireEvent.click(within(form).getByRole("button", { name: /Загрузить$/ }));
    await modalClosed("Загрузить файл");

    // фильтр ?product_id=1 оставляет и сертификат кабеля, и новый файл
    expect(await screen.findByRole("button", { name: "Открыть файл «Схема шкафа»" })).toBeVisible();
    expect(within(row("Схема шкафа")).getByText("28.10.2026")).toBeVisible();
  });

  it("слишком большой файл и неподходящий тип отсекаются до отправки, словами", async () => {
    await open("engineer@demo.example", "?product_id=1");
    fireEvent.click(await screen.findByRole("button", { name: "Загрузить файл" }));
    const form = await findModal("Загрузить файл");
    const input = await within(form).findByLabelText("Файл");

    fireEvent.change(input, { target: { files: [pdfFile("huge.pdf", 21 * 1024 * 1024)] } });
    expect(await within(form).findByRole("alert")).toHaveTextContent("Файл больше 20 МБ");
    expect(within(form).getByRole("button", { name: /Загрузить$/ })).toBeDisabled();

    fireEvent.change(input, {
      target: { files: [new File(["MZ"], "virus.exe", { type: "application/octet-stream" })] },
    });
    expect(await within(form).findByRole("alert")).toHaveTextContent("Подходят PDF, PNG, JPEG");
  });

  it("без привязки к позиции или заявке кнопка «Загрузить» неактивна и подсказка рядом", async () => {
    await open("engineer@demo.example");
    fireEvent.click(await screen.findByRole("button", { name: "Загрузить файл" }));
    const form = await findModal("Загрузить файл");
    fireEvent.change(await within(form).findByLabelText("Файл"), {
      target: { files: [pdfFile()] },
    });
    expect(await within(form).findByText(/Нужна хотя бы одна привязка/)).toBeInTheDocument();
    expect(within(form).getByRole("button", { name: /Загрузить$/ })).toBeDisabled();
  });

  it("документ Word не открывается для просмотра, его скачивают", async () => {
    await open("engineer@demo.example", "?product_id=1");
    fireEvent.click(await screen.findByRole("button", { name: "Загрузить файл" }));
    const form = await findModal("Загрузить файл");
    fireEvent.change(await within(form).findByLabelText("Файл"), {
      target: {
        files: [
          new File(["PK"], "reglament.docx", {
            type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          }),
        ],
      },
    });
    fireEvent.click(await within(form).findByRole("button", { name: /Загрузить$/ }));
    await modalClosed("Загрузить файл");

    fireEvent.click(await screen.findByRole("button", { name: "Открыть файл «reglament»" }));
    const drawer = await screen.findByRole("dialog", { name: "reglament" });
    expect(
      await within(drawer).findByText(/Этот формат не открывается для просмотра/),
    ).toBeVisible();
    expect(within(drawer).queryByTestId("pdf-stub")).toBeNull();
  });

  it("удаление: окно «Что произойдёт», после подтверждения файла нет в списке", async () => {
    await open("engineer@demo.example", "?doc=4");
    const drawer = await screen.findByRole("dialog", { name: "Регламент ПНР устройств СЦБ" });
    fireEvent.click(await within(drawer).findByRole("button", { name: "Удалить файл" }));
    const confirm = await findModal(/Удалить файл «Регламент ПНР/);
    expect(await within(confirm).findByText("Что произойдёт")).toBeInTheDocument();
    fireEvent.click(await within(confirm).findByRole("button", { name: /Удалить файл$/ }));
    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: "Открыть файл «Регламент ПНР устройств СЦБ»" }),
      ).toBeNull();
    });
  });
});

describe("Техдокументация: телефон", () => {
  it("на 390 px — карточки, окно просмотра во всю ширину", async () => {
    setViewportWidth(390);
    await open("manager@demo.example");
    expect(
      await screen.findByRole("button", { name: /Открыть файл «ТЗ на стрелочные/ }),
    ).toBeVisible();
    expect(screen.queryByRole("table")).toBeNull();
  });
});
