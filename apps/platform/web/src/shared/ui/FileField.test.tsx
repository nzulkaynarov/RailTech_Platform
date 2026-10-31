import { fireEvent, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { renderUi } from "../../test/renderUi";
import { acceptLabel, matchesAccept } from "../lib/fileAccept";
import { FileField, FilePicker } from "./FileField";

const pdf = (name = "dogovor.pdf", size = 2048) =>
  new File([new Uint8Array(size)], name, { type: "application/pdf" });

function pick(input: HTMLElement, files: File[]) {
  fireEvent.change(input, { target: { files } });
}

function Controlled(props: {
  multiple?: boolean;
  maxSize?: number;
  accept?: string;
  onFiles?: (files: File[]) => void;
}) {
  const [files, setFiles] = useState<File[]>([]);
  return (
    <>
      <label htmlFor="scan">Скан</label>
      <FileField
        id="scan"
        value={files}
        multiple={props.multiple}
        maxSize={props.maxSize}
        accept={props.accept}
        aria-describedby="scan-hint"
        onChange={(next) => {
          setFiles(next);
          props.onFiles?.(next);
        }}
      />
      <span id="scan-hint">PDF до 1 МБ</span>
    </>
  );
}

describe("FileField", () => {
  it("кнопка «Выбрать файл» вместо системного поля, подпись ведёт к полю выбора", () => {
    renderUi(<Controlled />);
    expect(screen.getByRole("button", { name: "Выбрать файл" })).toBeVisible();
    const input = screen.getByLabelText("Скан");
    expect(input).toHaveAttribute("type", "file");
    expect(input).toHaveClass("pf-sr-only");
    expect(input).toHaveAttribute("tabindex", "-1");
  });

  it("выбор: список с размером, файлы — наружу как File[]", () => {
    const onFiles = vi.fn();
    renderUi(<Controlled multiple onFiles={onFiles} />);
    expect(screen.getByRole("button", { name: "Выбрать файлы" })).toBeVisible();
    pick(screen.getByLabelText("Скан"), [pdf("a.pdf", 1536), pdf("b.pdf", 3 * 1024 * 1024)]);
    const list = screen.getByRole("list", { name: "Выбранные файлы" });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("a.pdf1,5 КБУбрать");
    expect(items[1]).toHaveTextContent("b.pdf3 МБ");
    const [files] = onFiles.mock.lastCall as [File[]];
    expect(files.map((f) => f.name)).toEqual(["a.pdf", "b.pdf"]);
    pick(screen.getByLabelText("Скан"), [pdf("c.pdf")]);
    expect(within(list).getAllByRole("listitem")).toHaveLength(3);
  });

  it("один файл: новый выбор заменяет прежний, кнопка — «Выбрать другой файл»", () => {
    renderUi(<Controlled />);
    pick(screen.getByLabelText("Скан"), [pdf("a.pdf")]);
    pick(screen.getByLabelText("Скан"), [pdf("b.pdf")]);
    const list = screen.getByRole("list", { name: "Выбранные файлы" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(1);
    expect(list).toHaveTextContent("b.pdf");
    expect(screen.getByRole("button", { name: "Выбрать другой файл" })).toBeVisible();
  });

  it("«Убрать» снимает файл из списка", () => {
    const onFiles = vi.fn();
    renderUi(<Controlled multiple onFiles={onFiles} />);
    pick(screen.getByLabelText("Скан"), [pdf("a.pdf"), pdf("b.pdf")]);
    fireEvent.click(screen.getByRole("button", { name: "Убрать файл a.pdf" }));
    expect(onFiles).toHaveBeenLastCalledWith([expect.objectContaining({ name: "b.pdf" })]);
    fireEvent.click(screen.getByRole("button", { name: "Убрать файл b.pdf" }));
    expect(screen.queryByRole("list", { name: "Выбранные файлы" })).toBeNull();
  });

  it("maxSize: большой файл не берётся, ошибка словами и связана с кнопкой", () => {
    const onFiles = vi.fn();
    renderUi(<Controlled maxSize={1024 * 1024} onFiles={onFiles} />);
    pick(screen.getByLabelText("Скан"), [pdf("big.pdf", 2 * 1024 * 1024)]);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Файл «big.pdf» больше 1 МБ — выберите файл поменьше");
    expect(onFiles).not.toHaveBeenCalled();
    const button = screen.getByRole("button", { name: "Выбрать файл" });
    expect(button.getAttribute("aria-describedby")).toContain(alert.id);
    expect(screen.getByLabelText("Скан")).toHaveAttribute("aria-invalid", "true");
    pick(screen.getByLabelText("Скан"), [pdf("ok.pdf", 1000)]);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(onFiles).toHaveBeenCalledTimes(1);
  });

  it("accept: передаётся в системный диалог, файл не того типа при перетаскивании не берётся", () => {
    const onFiles = vi.fn();
    const { container } = renderUi(<Controlled accept=".pdf,image/*" onFiles={onFiles} />);
    expect(screen.getByLabelText("Скан")).toHaveAttribute("accept", ".pdf,image/*");
    const zone = container.querySelector(".pf-file-field") as HTMLElement;
    const doc = new File(["x"], "tz.docx", { type: "application/msword" });
    fireEvent.drop(zone, { dataTransfer: { files: [doc] } });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Файл «tz.docx» не подходит: можно PDF, IMAGE/*",
    );
    expect(onFiles).not.toHaveBeenCalled();
    fireEvent.drop(zone, {
      dataTransfer: { files: [new File(["x"], "foto.png", { type: "image/png" })] },
    });
    expect(onFiles).toHaveBeenLastCalledWith([expect.objectContaining({ name: "foto.png" })]);
  });

  it("узбекский текст кнопки", () => {
    renderUi(<Controlled multiple />, { language: "uz" });
    expect(screen.getByRole("button", { name: "Fayllarni tanlash" })).toBeVisible();
  });
});

describe("FilePicker", () => {
  it("своя подпись поля и кнопки, выбор — в onPick", () => {
    const onPick = vi.fn();
    renderUi(
      <FilePicker inputLabel="Выбрать файл: Логотип" buttonLabel="Загрузить" onPick={onPick} />,
      { language: "en" },
    );
    expect(screen.getByRole("button", { name: "Загрузить" })).toBeVisible();
    pick(screen.getByLabelText("Выбрать файл: Логотип"), [pdf()]);
    expect(onPick).toHaveBeenCalledWith([expect.objectContaining({ name: "dogovor.pdf" })]);
  });

  it("кнопка открывает системный диалог", () => {
    renderUi(<FilePicker inputLabel="Файл" onPick={() => undefined} />);
    const input = screen.getByLabelText("Файл");
    const click = vi.spyOn(input, "click");
    fireEvent.click(screen.getByRole("button", { name: "Выбрать файл" }));
    expect(click).toHaveBeenCalled();
  });
});

describe("matchesAccept и acceptLabel", () => {
  it("расширения, маски и типы", () => {
    expect(matchesAccept(pdf("A.PDF"), ".pdf")).toBe(true);
    expect(matchesAccept(pdf(), "image/*")).toBe(false);
    expect(
      matchesAccept(new File(["{}"], "k.json", { type: "application/json" }), "application/json"),
    ).toBe(true);
    expect(matchesAccept(pdf(), undefined)).toBe(true);
    expect(acceptLabel(".md,text/markdown")).toBe("MD, MARKDOWN");
    expect(acceptLabel("image/png,image/svg+xml")).toBe("PNG, SVG");
  });
});
