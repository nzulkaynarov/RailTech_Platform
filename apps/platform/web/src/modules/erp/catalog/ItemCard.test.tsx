import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { http } from "msw";
import { describe, expect, it } from "vitest";

import { chooseOption, fillDate, selectedLabel } from "../../../test/fields";
import { readErpCatalog } from "../../../mocks/fixtures/erpCatalog";
import { server } from "../../../test/server";
import {
  findModal,
  modalClosed,
  renderAt,
  setupCatalogTests,
  signIn,
} from "../../../test/catalogKit";

setupCatalogTests();

const png = (name: string, size = 64) =>
  new File([new Uint8Array(size).fill(1)], name, { type: "image/png" });
const pdf = (name: string) =>
  new File([new Uint8Array(32).fill(37)], name, { type: "application/pdf" });

/** Текстовые поля multipart-тела (файл пропускается): `name="поле"\r\n\r\nзначение`. */
function formFields(raw: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const part of raw.split(/--[-\w]+/)) {
    const found = /name="([^"]+)"(?!; filename)\r\n\r\n([\s\S]*?)\r\n$/.exec(part);
    if (found?.[1] && found[2] !== undefined && !part.includes("filename="))
      out[found[1]] = found[2];
  }
  return out;
}

/** Карточка позиции RT-0001 (кабель, три фото) в боковом окне. */
async function openCable(email: string) {
  signIn(email);
  renderAt("/erp/catalog?item=1");
  return screen.findByRole("dialog", { name: "Кабель силовой ВВГнг 3×2,5" });
}

async function photos(drawer: HTMLElement) {
  return within(await within(drawer).findByRole("list", { name: "Фото позиции" })).findAllByRole(
    "listitem",
  );
}

describe("Карточка товара: фото", () => {
  it("счётчик, главное фото помечено словом, подсказка про размер и фон", async () => {
    const drawer = await openCable("supply@demo.example");
    const items = await photos(drawer);

    expect(items).toHaveLength(3);
    expect(await within(drawer).findByText("3 из 10")).toBeVisible();
    expect(within(items[0] as HTMLElement).getByText("Главное")).toBeVisible();
    expect(within(drawer).getAllByText("Главное")).toHaveLength(1);
    expect(within(drawer).getByText(/квадрат от 900 px на светлом фоне/)).toBeVisible();
    expect(within(items[0] as HTMLElement).getByRole("img")).toHaveAttribute(
      "src",
      "/api/v1/erp/catalog/items/1/images/101/content",
    );
  });

  it("сделать главным и поменять порядок: звезда переходит, список переставляется", async () => {
    const drawer = await openCable("supply@demo.example");
    await photos(drawer);

    fireEvent.click(within(drawer).getByRole("button", { name: "Сделать главным фото 3" }));
    await waitFor(async () => {
      const items = await photos(drawer);
      expect(within(items[2] as HTMLElement).getByText("Главное")).toBeVisible();
    });
    expect(within(drawer).getAllByText("Главное")).toHaveLength(1);

    fireEvent.click(within(drawer).getByRole("button", { name: "Поднять фото 3" }));
    await waitFor(async () => {
      const items = await photos(drawer);
      expect(within(items[1] as HTMLElement).getByText("Главное")).toBeVisible();
    });
    expect(within(drawer).getByRole("button", { name: "Поднять фото 1" })).toBeDisabled();
  });

  it("удаление главного — с подтверждением; главным становится следующее", async () => {
    const drawer = await openCable("supply@demo.example");
    await photos(drawer);

    fireEvent.click(within(drawer).getByRole("button", { name: "Удалить фото 1" }));
    const confirm = await findModal("Удалить фото 1?");
    expect(await within(confirm).findByText("Что произойдёт")).toBeInTheDocument();
    expect(within(confirm).getByText(/главным станет следующее/)).toBeInTheDocument();
    fireEvent.click(within(confirm).getByRole("button", { name: "Удалить" }));
    await modalClosed("Удалить фото 1?");

    await waitFor(async () => {
      expect(await photos(drawer)).toHaveLength(2);
    });
    expect(await within(drawer).findByText("2 из 10")).toBeVisible();
    const items = await photos(drawer);
    expect(within(items[0] as HTMLElement).getByText("Главное")).toBeVisible();
  });

  it("загрузка: файл добавляется в конец; больше десяти — кнопка закрыта и сказано словами", async () => {
    const drawer = await openCable("supply@demo.example");
    await photos(drawer);

    const input = drawer.querySelector<HTMLInputElement>('input[type="file"]');
    if (!input) throw new Error("нет поля файла");
    fireEvent.change(input, {
      target: { files: Array.from({ length: 7 }, (_, n) => png(`extra-${String(n)}.png`)) },
    });

    await waitFor(async () => {
      expect(await photos(drawer)).toHaveLength(10);
    });
    expect(within(drawer).getByRole("button", { name: /Добавить фото/ })).toBeDisabled();
    expect(within(drawer).getByText(/Достигнут предел: 10 фото/)).toBeVisible();
  });

  it("не изображение и слишком большой файл отсекаются до отправки, словами", async () => {
    const drawer = await openCable("supply@demo.example");
    await photos(drawer);
    const input = drawer.querySelector<HTMLInputElement>('input[type="file"]');
    if (!input) throw new Error("нет поля файла");

    fireEvent.change(input, {
      target: { files: [new File(["<svg/>"], "logo.svg", { type: "image/svg+xml" })] },
    });
    expect(await within(drawer).findByText(/Подходят PDF, PNG, JPEG/)).toBeVisible();

    fireEvent.change(input, { target: { files: [png("huge.png", 6 * 1024 * 1024)] } });
    expect(await within(drawer).findByText(/Файл больше 20 МБ|больше 5 МБ/)).toBeVisible();
    expect(await photos(drawer)).toHaveLength(3);
  });

  it("менеджер видит фото, но не меняет: кнопок изменения нет", async () => {
    const drawer = await openCable("manager@demo.example");
    await photos(drawer);

    expect(within(drawer).queryByRole("button", { name: "Добавить фото" })).toBeNull();
    expect(within(drawer).queryByRole("button", { name: /Удалить фото/ })).toBeNull();
    expect(within(drawer).queryByRole("button", { name: /Сделать главным/ })).toBeNull();
  });
});

describe("Карточка товара: документы", () => {
  it("документ с номером, сроком и пометкой «Видно клиенту» виден в карточке", async () => {
    const drawer = await openCable("manager@demo.example");
    const docs = await within(drawer).findByRole("list", { name: "Документы позиции" });

    expect(within(docs).getByText("Сертификат соответствия на кабель")).toBeVisible();
    expect(within(docs).getByText("Сертификат соответствия")).toBeVisible();
    expect(within(docs).getByText(/RU-0042-2026/)).toBeVisible();
    expect(within(docs).getByText(/до 11\.01\.2027/)).toBeVisible();
    expect(within(docs).getByText(/Видно клиенту/)).toBeVisible();
  });

  it("загрузка из карточки: вид, номер, кем выдан, срок; «Видно клиенту» подставляется по виду", async () => {
    let sent: Record<string, string> | null = null;
    server.use(
      http.post("*/erp/docs/files", async ({ request }) => {
        sent = formFields(await request.clone().text());
        return undefined;
      }),
    );
    const drawer = await openCable("supply@demo.example");
    fireEvent.click(await within(drawer).findByRole("button", { name: "Добавить документ" }));

    const form = await findModal("Добавить документ");
    fireEvent.change(await within(form).findByLabelText("Файл"), {
      target: { files: [pdf("decl.pdf")] },
    });
    await chooseOption(within(form).getByLabelText("Вид"), "Декларация о соответствии");
    expect(within(form).getByRole("checkbox", { name: "Видно клиенту" })).toBeChecked();
    await chooseOption(within(form).getByLabelText("Вид"), "Чертёж");
    expect(within(form).getByRole("checkbox", { name: "Видно клиенту" })).not.toBeChecked();
    await chooseOption(within(form).getByLabelText("Вид"), "Сертификат соответствия");
    fireEvent.change(within(form).getByLabelText("Номер"), { target: { value: "ДС-77" } });
    fireEvent.change(within(form).getByLabelText("Кем выдан"), {
      target: { value: "Орган по сертификации" },
    });
    fillDate(within(form).getByLabelText("Выдан"), "2026-10-01");
    fillDate(within(form).getByLabelText("Действует до"), "2027-10-01");
    fireEvent.click(within(form).getByRole("button", { name: /Загрузить$/ }));
    await modalClosed("Добавить документ");

    expect(sent).toEqual({
      product_id: "1",
      title: "decl",
      kind: "certificate",
      number: "ДС-77",
      issued_by: "Орган по сертификации",
      issued_at: "2026-10-01",
      valid_until: "2027-10-01",
      client_visible: "true",
    });
    expect(await within(drawer).findByText("decl")).toBeVisible();
  });

  it("срок вышел — пометка «Истёк» у сотрудника; правка срока её снимает", async () => {
    const drawer = await openCable("supply@demo.example");
    fireEvent.click(await within(drawer).findByRole("button", { name: "Добавить документ" }));
    const form = await findModal("Добавить документ");
    fireEvent.change(await within(form).findByLabelText("Файл"), {
      target: { files: [pdf("old.pdf")] },
    });
    await chooseOption(within(form).getByLabelText("Вид"), "Сертификат соответствия");
    fillDate(within(form).getByLabelText("Действует до"), "2026-01-01");
    fireEvent.click(within(form).getByRole("button", { name: /Загрузить$/ }));
    await modalClosed("Добавить документ");

    const docs = await within(drawer).findByRole("list", { name: "Документы позиции" });
    const old = (await within(docs).findByText("old")).closest("li") as HTMLElement;
    expect(within(old).getByText("Истёк")).toBeVisible();

    fireEvent.click(within(old).getByRole("button", { name: "Изменить документ «old»" }));
    const edit = await findModal("Изменить документ");
    fillDate(within(edit).getByLabelText("Действует до"), "2030-01-01");
    fireEvent.click(within(edit).getByRole("button", { name: "Сохранить" }));
    await modalClosed("Изменить документ");

    await waitFor(() => {
      expect(within(old).queryByText("Истёк")).toBeNull();
    });
    expect(within(old).getByText(/до 01\.01\.2030/)).toBeVisible();
  });
});

describe("Карточка товара: документ выключенного вида", () => {
  it("в форме «Изменить» вид показан названием, а не кодом; номер и срок правятся", async () => {
    let sent: unknown = null;
    server.use(
      http.patch("*/erp/docs/files/:id", async ({ request }) => {
        sent = await request.clone().json();
        return Response.json({}, { status: 500 });
      }),
    );
    // вид, которого уже нет в справочнике активных (его выключили): документ остаётся
    readErpCatalog().docs.push({
      bytes: new Uint8Array(),
      doc: {
        id: "77",
        title: "Старый регламент",
        kind: "legacy",
        kind_name: "Старый вид документа",
        number: "Л-1",
        issued_by: "",
        issued_at: null,
        valid_until: null,
        is_expired: false,
        client_visible: false,
        original_name: "old.pdf",
        content_type: "application/pdf",
        size_bytes: 10,
        previewable: true,
        product: { id: "1", name: "Кабель силовой ВВГнг 3×2,5", sku: "RT-0001" },
        dealId: null,
        uploaded_by: "Снабженец",
        created_at: "2026-10-01T09:00:00Z",
      },
    });
    const drawer = await openCable("supply@demo.example");
    fireEvent.click(
      await within(drawer).findByRole("button", { name: "Изменить документ «Старый регламент»" }),
    );

    const form = await findModal("Изменить документ");
    const kind = within(form).getByRole("combobox", { name: "Вид" });
    expect(selectedLabel(kind)).toBe("Старый вид документа");
    expect(within(form).queryByText("legacy")).toBeNull();
    fireEvent.change(within(form).getByLabelText("Номер"), { target: { value: "Л-2" } });
    fireEvent.click(within(form).getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(sent).toMatchObject({ kind: "legacy", number: "Л-2" });
    });
  });
});

describe("Карточка товара: страна происхождения и гарантия", () => {
  it("по умолчанию — страна изготовителя и срок компании, источник назван словами", async () => {
    const drawer = await openCable("manager@demo.example");

    expect(await within(drawer).findByText("Страна происхождения")).toBeVisible();
    expect(within(drawer).getByText("12 мес. (по умолчанию компании)")).toBeVisible();
  });

  it("форма: подсказки с умолчанием, отправляется только изменённое", async () => {
    let sent: unknown = null;
    server.use(
      http.patch("*/erp/catalog/items/:id", async ({ request }) => {
        sent = await request.clone().json();
        return undefined;
      }),
    );
    const drawer = await openCable("supply@demo.example");
    fireEvent.click(await within(drawer).findByRole("button", { name: "Изменить позицию" }));

    const form = await findModal("Изменить позицию");
    expect(await within(form).findByText(/Пусто — 12 мес., как у компании/)).toBeInTheDocument();
    await chooseOption(within(form).getByLabelText("Страна происхождения"), "Германия");
    fireEvent.change(within(form).getByLabelText("Гарантия, мес."), { target: { value: "24" } });
    fireEvent.change(within(form).getByLabelText("Условия гарантии"), {
      target: { value: "Замена при браке" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Сохранить" }));

    await waitFor(() => {
      expect(sent).toEqual({
        country_of_origin_id: "3",
        warranty_months: 24,
        warranty_terms: "Замена при браке",
      });
    });
    await modalClosed("Изменить позицию");
    expect(await within(drawer).findByText("24 мес.")).toBeVisible();
    expect(within(drawer).getByText("Германия")).toBeVisible();
  });

  it("гарантия вне 0–600 не уходит: поле помечено, кнопка закрыта", async () => {
    const drawer = await openCable("supply@demo.example");
    fireEvent.click(await within(drawer).findByRole("button", { name: "Изменить позицию" }));
    const form = await findModal("Изменить позицию");
    fireEvent.change(await within(form).findByLabelText("Гарантия, мес."), {
      target: { value: "700" },
    });
    expect(within(form).getByRole("button", { name: "Сохранить" })).toBeDisabled();
  });
});
