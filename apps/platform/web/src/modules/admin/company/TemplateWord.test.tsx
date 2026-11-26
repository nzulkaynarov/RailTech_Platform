import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { usePanelsStore } from "../../../app/shell/panelsStore";
import { resetContractTemplates } from "../../../mocks/contractTemplates";
import { resetSampleMock } from "../../../mocks/adminCompany";
import { readCompanyMock, resetCompanyMock } from "../../../mocks/fixtures/company";
import { endSession } from "../../../mocks/mockSession";
import type { TemplateWordCheck } from "../../../shared/api/generated/model";
import i18n from "../../../shared/i18n";
import { pickRowAction, rowActionItems } from "../../../test/rowActions";
import { renderApp, signInAs } from "../../../test/renderApp";
import { setViewportWidth } from "../../../test/viewport";
import { templateFileName } from "./templateWord";

vi.mock("../../../shared/ui/PdfViewer", () => ({
  default: ({ name }: { name: string }) => <div data-testid="pdf-pages">{name}</div>,
}));

beforeEach(() => {
  window.localStorage.clear();
  resetCompanyMock();
  resetContractTemplates();
  resetSampleMock();
  usePanelsStore.setState({ entries: {} });
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
});
afterEach(() => {
  vi.restoreAllMocks();
  endSession();
});

const CHECK: TemplateWordCheck = {
  unchanged: false,
  formatting_only: false,
  can_apply: true,
  locked: false,
  base: "0123456789abcdef",
  file_sha: "fedcba9876543210",
  dropped: [],
  lost_markup: [],
  unknown_placeholders: [],
  missing_blocks: [],
  summary: { changed: ["1"], added: ["3"], removed: [], total: 2, more: 0 },
  items: [
    {
      point: "1",
      kind: "changed",
      ours: "1. Поставка товаров.",
      theirs: "1. Поставка и монтаж товаров.",
      segments: [
        { op: "equal", text: "1. Поставка " },
        { op: "ins", text: "и монтаж " },
        { op: "equal", text: "товаров." },
      ],
    },
    { point: "3", kind: "added", ours: "", theirs: "3. Гарантия.", segments: [] },
  ],
};

/**
 * Загрузка файла: `FormData` jsdom не понимает встроенный в Node `fetch` (как у логотипа), поэтому два адреса Word
 * перехватываются на уровне `fetch`; настоящий `multipart` через MSW проверяет e2e.
 */
function stubWord(check: Partial<TemplateWordCheck> = {}, refusal?: string) {
  const original = globalThis.fetch;
  const calls: { url: string; file: string }[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = typeof input === "string" ? input : "";
    if (/\/word\/(check|apply)\?/.test(url) && init?.method === "POST") {
      calls.push({ url, file: ((init.body as FormData).get("file") as File).name });
      if (refusal) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              code: "VALIDATION_FAILED",
              message: "x",
              source: "erp",
              details: { reason: refusal },
            }),
            { status: 422, headers: { "content-type": "application/json" } },
          ),
        );
      }
      const body = url.includes("/word/check")
        ? { ...CHECK, ...check }
        : { ...readCompanyMock().docTemplates[1], body_html: "<p>Новый текст</p>" };
      return Promise.resolve(
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
    }
    return original(input, init);
  });
  return calls;
}

async function openEditor(id = "2") {
  signInAs("admin@demo.example");
  const app = renderApp(`/admin/templates?tab=documents&edit=${id}`);
  await screen.findByRole("heading", { name: "Изменить шаблон документа" });
  return app;
}

function pick(name: string, text = "x") {
  // в редакторе выбор файла начинается кнопкой; в списке договоров — пунктом меню строки (его нажимает тест)
  const button = screen.queryByRole("button", { name: "Загрузить из Word" });
  if (button) fireEvent.click(button);
  const input = screen.getByLabelText("Файл Word");
  fireEvent.change(input, {
    target: { files: [new File([text], name, { type: "application/octet-stream" })] },
  });
}

describe("шаблон в Word (ШАБЛ-1): редактор шаблона документа", () => {
  it("разметка спрятана, пока не попросят; основной путь — Word", async () => {
    await openEditor();
    const markup = screen.getByLabelText(/^Текст шаблона \(HTML\)/);
    expect(markup).not.toBeVisible();
    expect(screen.getByRole("button", { name: "Скачать Word" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Загрузить из Word" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Показать разметку" }));
    expect(screen.getByLabelText(/^Текст шаблона \(HTML\)/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Скрыть разметку" }));
    expect(screen.getByLabelText(/^Текст шаблона \(HTML\)/)).not.toBeVisible();
  });

  it("скрытая разметка уходит при сохранении: правка названия не стирает текст", async () => {
    await openEditor();
    fireEvent.change(screen.getByLabelText("Название"), { target: { value: "Договор (новый)" } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await screen.findByText("Сохранено");
    const row = readCompanyMock().docTemplates.find((t) => t.id === "2");
    expect(row?.name).toBe("Договор (новый)");
    expect(row?.body_html).toContain("Срок: {{delivery_term}}");
  });

  it("«Скачать Word» сохраняет файл под именем по правилу", async () => {
    await openEditor();
    const names: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      names.push(this.download);
    });
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    fireEvent.click(screen.getByRole("button", { name: "Скачать Word" }));
    await waitFor(() => {
      expect(names).toEqual(["Договор поставки (наш), ред. 1 — проект.docx"]);
    });
  });

  it("загрузка: сначала «что изменилось», сохранение только после «Принять изменения»", async () => {
    await openEditor();
    const calls = stubWord();
    pick("Правки юриста.docx");
    const sheet = await screen.findByRole("dialog", { name: /Что изменилось · RU/ });
    expect(within(sheet).getByText("Изменено: 1 · добавлено: 1 · удалено: 0")).toBeInTheDocument();
    expect(within(sheet).getByText("Пункт 1 · изменён")).toBeInTheDocument();
    expect(within(sheet).getByText("и монтаж")).toBeInTheDocument();
    expect(within(sheet).getByText("Пункт 3 · добавлен")).toBeInTheDocument();
    expect(calls.map((c) => c.url)).toEqual([
      "/api/v1/document-templates/2/word/check?language=ru",
    ]);
    expect(readCompanyMock().docTemplates.find((t) => t.id === "2")?.body_html).toContain("Срок");

    fireEvent.click(within(sheet).getByRole("button", { name: "Принять изменения" }));
    await screen.findByText("Текст шаблона обновлён");
    expect(calls[1]?.url).toBe(
      "/api/v1/document-templates/2/word/apply?language=ru&base=0123456789abcdef&file_sha=fedcba9876543210",
    );
    expect(calls[1]?.file).toBe("Правки юриста.docx");
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: /Что изменилось/ })).toBeNull();
    });
    expect(screen.getByLabelText(/^Текст шаблона \(HTML\)/)).toHaveValue("<p>Новый текст</p>");
  });

  it("«Отмена» ничего не сохраняет", async () => {
    await openEditor();
    const calls = stubWord();
    pick("a.docx");
    const sheet = await screen.findByRole("dialog", { name: /Что изменилось/ });
    fireEvent.click(within(sheet).getByRole("button", { name: "Отмена" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: /Что изменилось/ })).toBeNull();
    });
    expect(calls).toHaveLength(1); // только проверка
  });

  it("без изменений: так и сказано, «Принять» недоступно", async () => {
    await openEditor();
    stubWord({
      unchanged: true,
      can_apply: false,
      summary: { changed: [], added: [], removed: [], total: 0, more: 0 },
      items: [],
    });
    pick("a.docx");
    const sheet = await screen.findByRole("dialog", { name: /Что изменилось/ });
    expect(
      within(sheet).getByText("Изменений нет: файл совпадает с текстом шаблона."),
    ).toBeInTheDocument();
    expect(within(sheet).getByRole("button", { name: "Принять изменения" })).toBeDisabled();
  });

  it("неизвестные подстановки названы по именам; недостающие блоки — тоже", async () => {
    await openEditor();
    stubWord({
      unknown_placeholders: ["warehouse_name", "deal_sum"],
      missing_blocks: [{ code: "doc.totals", label: "Блок: итоги и НДС" }],
      can_apply: false,
      dropped: [
        { kind: "images", count: 2 },
        { kind: "colors", count: 1 },
      ],
    });
    pick("a.docx");
    const sheet = await screen.findByRole("dialog", { name: /Что изменилось/ });
    expect(within(sheet).getByText("Неизвестные поля: 2")).toBeInTheDocument();
    expect(within(sheet).getByText("{{warehouse_name}}")).toBeInTheDocument();
    expect(within(sheet).getByText("{{deal_sum}}")).toBeInTheDocument();
    expect(within(sheet).getByText("Блок: итоги и НДС")).toBeInTheDocument();
    expect(within(sheet).getByText("Рисунки: 2")).toBeInTheDocument();
    expect(within(sheet).getByText("Цвет текста: 1")).toBeInTheDocument();
    expect(within(sheet).getByRole("button", { name: "Принять изменения" })).toBeDisabled();
  });

  it("в текущем тексте есть ссылки и рисунки: принять можно только после подтверждения, оно уходит в запрос", async () => {
    await openEditor();
    const calls = stubWord({
      lost_markup: [
        { kind: "links", count: 2 },
        { kind: "merged_cells", count: 1 },
      ],
    });
    pick("a.docx");
    const sheet = await screen.findByRole("dialog", { name: /Что изменилось/ });
    expect(within(sheet).getByText("Ссылки: 2")).toBeInTheDocument();
    expect(within(sheet).getByText("Объединённые ячейки: 1")).toBeInTheDocument();
    const accept = within(sheet).getByRole("button", { name: "Принять изменения" });
    expect(accept).toBeDisabled();
    fireEvent.click(within(sheet).getByRole("checkbox", { name: "Понимаю, это пропадёт" }));
    expect(accept).toBeEnabled();
    fireEvent.click(accept);
    await screen.findByText("Текст шаблона обновлён");
    expect(calls[1]?.url).toBe(
      "/api/v1/document-templates/2/word/apply?language=ru&base=0123456789abcdef&file_sha=fedcba9876543210&confirm_loss=true",
    );
  });

  it("слова те же, но в файле цвета и комментарии: «изменений нет» не говорится, принять нечего", async () => {
    await openEditor();
    stubWord({
      unchanged: false,
      can_apply: false,
      summary: { changed: [], added: [], removed: [], total: 0, more: 0 },
      items: [],
      dropped: [
        { kind: "comments", count: 1 },
        { kind: "highlights", count: 3 },
      ],
    });
    pick("a.docx");
    const sheet = await screen.findByRole("dialog", { name: /Что изменилось/ });
    expect(within(sheet).queryByText(/Изменений нет/)).toBeNull();
    expect(
      within(sheet).getByText(/Слова те же, но в файле есть то, что не сохраняется/),
    ).toBeInTheDocument();
    expect(within(sheet).getByText("Комментарии: 1")).toBeInTheDocument();
    expect(within(sheet).getByText("Выделение цветом: 3")).toBeInTheDocument();
    expect(within(sheet).getByRole("button", { name: "Принять изменения" })).toBeDisabled();
  });

  it("обрывки полей называются как есть, коды — в фигурных скобках", async () => {
    await openEditor();
    stubWord({ unknown_placeholders: ["{{buyer name}", "deal_sum"], can_apply: true });
    pick("a.docx");
    const sheet = await screen.findByRole("dialog", { name: /Что изменилось/ });
    expect(within(sheet).getByText("{{buyer name}")).toBeInTheDocument();
    expect(within(sheet).getByText("{{deal_sum}}")).toBeInTheDocument();
  });

  it("файл скачан до чужой правки: сказано словами, панель не открывается", async () => {
    await openEditor();
    stubWord({}, "word_stale");
    pick("old.docx");
    expect(
      await screen.findByText(/Шаблон изменился после скачивания: скачайте его заново/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: /Что изменилось/ })).toBeNull();
  });

  it("плохой файл: понятная причина, панель не открывается", async () => {
    await openEditor();
    stubWord({}, "word_hostile");
    pick("bomb.docx");
    expect(
      await screen.findByText(/Файл не похож на документ Word или слишком сложный/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: /Что изменилось/ })).toBeNull();
  });

  it("вкладка языка: файл и загрузка идут на выбранном языке", async () => {
    await openEditor();
    const calls = stubWord();
    fireEvent.click(screen.getByText(/^UZ/, { selector: ".ant-segmented-item-label" }));
    expect(screen.getByText(/На этом языке текста пока нет/)).toBeInTheDocument();
    pick("uz.docx");
    await screen.findByRole("dialog", { name: /Что изменилось · UZ/ });
    expect(calls[0]?.url).toContain("language=uz");
  });

  it("образец платформы: скачать можно, загрузить нельзя; шаблон без права — тоже", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/templates?tab=documents&edit=1");
    await screen.findByRole("region", { name: "Образец платформы" });
    expect(screen.getByRole("button", { name: "Скачать Word" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Загрузить из Word" })).toBeNull();
  });

  it("новый шаблон: сначала сохранить", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/templates?tab=documents&edit=new");
    expect(await screen.findByText(/Сохраните шаблон — после этого/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Скачать Word" })).toBeNull();
  });
});

describe("шаблон в Word (ШАБЛ-1): шаблоны договоров", () => {
  async function rowOf(name: string): Promise<HTMLElement> {
    const table = await screen.findByRole("table", { name: "Шаблоны договоров" });
    return within(table).getByRole("row", { name: new RegExp(name) });
  }

  it("утверждённый: скачать Word и PDF можно, загрузить — нет; черновик: можно всё", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/templates?tab=contracts");
    await rowOf("Договор с клиентом · поставка");
    expect(await rowActionItems("Договор с клиентом · поставка")).toEqual([
      "Скачать Word",
      "Скачать PDF",
      "Новая редакция",
    ]);
    expect(await rowActionItems("Договор с партнёром · услуги")).toEqual([
      "Скачать Word",
      "Скачать PDF",
      "Загрузить из Word",
      "На утверждение",
    ]);
  });

  it("язык файла выбирается над таблицей; загрузка в черновик идёт на этом языке", async () => {
    signInAs("admin@demo.example");
    renderApp("/admin/templates?tab=contracts");
    await rowOf("Договор с партнёром · услуги");
    fireEvent.click(screen.getByText("EN", { selector: ".ant-segmented-item-label" }));
    const calls = stubWord();
    await pickRowAction("Договор с партнёром · услуги", "Загрузить из Word");
    pick("en.docx");
    await screen.findByRole("dialog", { name: /Что изменилось · EN/ });
    expect(calls[0]?.url).toContain("/document-templates/");
    expect(calls[0]?.url).toContain("language=en");
  });
});

describe("имя файла — одно правило", () => {
  it("«<Название>, ред. <N> — проект», язык — в названии, запрещённые знаки убраны", () => {
    expect(templateFileName("Договор", 2, "ru", "docx")).toBe("Договор, ред. 2 — проект.docx");
    expect(templateFileName("Договор", 2, "uz", "pdf")).toBe("Договор (UZ), ред. 2 — проект.pdf");
    expect(templateFileName('Договор: "поставка"/2026', 3, "ru", "docx")).toBe(
      "Договор поставка 2026, ред. 3 — проект.docx",
    );
    expect(templateFileName("   ", 1, "en", "pdf")).toBe("Шаблон (EN), ред. 1 — проект.pdf");
  });
});
