import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { usePanelsStore } from "../../../app/shell/panelsStore";
import { resetEdsTemplatesMock } from "../../../mocks/edsTemplates";
import { endSession } from "../../../mocks/mockSession";
import i18n from "../../../shared/i18n";
import { renderApp, signInAs } from "../../../test/renderApp";
import { setViewportWidth } from "../../../test/viewport";

vi.mock("../../../shared/ui/PdfViewer", () => ({
  default: ({ name }: { name: string }) => <div data-testid="pdf-pages">{name}</div>,
}));

// Редактор в jsdom не принимает ввод (contenteditable): поле текста с тем же id и подписью, тело — абзацами
vi.mock("../../../shared/ui/BodyEditor/BodyEditor", async () => {
  const { paragraphOf } = await import("../../../shared/ui/BodyEditor/bodyModel");
  return {
    BodyEditor: ({
      id,
      label,
      value,
      onChange,
    }: {
      id: string;
      label: string;
      value: { content?: { content?: { text?: string }[] }[] };
      onChange: (doc: unknown) => void;
    }) => (
      <textarea
        id={id}
        aria-label={label}
        defaultValue={(value.content ?? [])
          .map((block) => (block.content ?? []).map((node) => node.text ?? "").join(""))
          .join("\n\n")}
        onChange={(event) => {
          onChange({ type: "doc", content: event.target.value.split("\n\n").map(paragraphOf) });
        }}
      />
    ),
  };
});

beforeEach(() => {
  window.localStorage.clear();
  resetEdsTemplatesMock();
  usePanelsStore.setState({ entries: {} });
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
});
afterEach(() => {
  endSession();
});

describe("Письма на бланке (TPL-4)", () => {
  it("шаблон — варианты по языкам и PDF на бланке; правка встроенного помечает «Изменён», «Вернуть» снимает", async () => {
    signInAs("director@demo.example");
    renderApp("/admin/templates?tab=letters");
    fireEvent.click(await screen.findByRole("button", { name: "Открыть: Деловое письмо" }));
    const dialog = await screen.findByRole("dialog", { name: "Деловое письмо" });
    expect(within(dialog).getByLabelText("Текст (RU)")).toHaveValue(
      "Уважаемые коллеги!\n\nСообщаем следующее.\n\nС уважением,",
    );
    fireEvent.click(within(dialog).getByText("UZ"));
    expect(await within(dialog).findByLabelText("Текст (UZ)")).toHaveValue(
      "Hurmatli hamkasblar!\n\nQuyidagilarni ma’lum qilamiz.\n\nHurmat bilan,",
    );
    expect(
      await within(dialog).findByTestId("pdf-pages", {}, { timeout: 3000 }),
    ).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: "Вернуть по умолчанию" }));
    const confirm = await screen.findByRole("dialog", {
      name: "Вернуть «Деловое письмо» по умолчанию?",
    });
    fireEvent.click(within(confirm).getByRole("button", { name: "Вернуть по умолчанию" }));
    expect(await screen.findByText("Шаблон возвращён")).toBeInTheDocument();

    fireEvent.change(within(dialog).getByLabelText("Текст (UZ)"), {
      target: { value: "Hurmatli hamkorlar!" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Сохранить шаблон" }));
    const row = await screen.findByRole("row", { name: /Деловое письмо/ });
    await waitFor(() => {
      expect(within(row).getByText("Изменён")).toBeInTheDocument();
    });
  });
});
