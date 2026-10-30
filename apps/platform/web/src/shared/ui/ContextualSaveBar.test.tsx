import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderUi as render } from "../../test/renderUi";
import { ContextualSaveBar } from "./ContextualSaveBar";

describe("ContextualSaveBar", () => {
  it("не рендерится при visible = false", () => {
    const onSave = vi.fn();
    const onDiscard = vi.fn();

    render(<ContextualSaveBar visible={false} onSave={onSave} onDiscard={onDiscard} />);

    expect(screen.queryByRole("region", { name: "Несохранённые изменения" })).toBeNull();
  });

  it("рендерится при visible = true со стандартными подписями и индикатором", () => {
    const onSave = vi.fn();
    const onDiscard = vi.fn();

    render(<ContextualSaveBar visible={true} onSave={onSave} onDiscard={onDiscard} />);

    const region = screen.getByRole("region", { name: "Несохранённые изменения" });
    expect(region).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Есть несохранённые изменения");
    expect(screen.getByRole("button", { name: "Отменить" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Сохранить изменения/ })).toBeInTheDocument();
  });

  it("поддерживает кастомные сообщения и подписи кнопок", () => {
    const onSave = vi.fn();
    const onDiscard = vi.fn();

    render(
      <ContextualSaveBar
        visible={true}
        message="Внесены правки в прайс-лист"
        saveLabel="Применить"
        discardLabel="Сбросить все"
        onSave={onSave}
        onDiscard={onDiscard}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("Внесены правки в прайс-лист");
    expect(screen.getByRole("button", { name: "Сбросить все" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Применить/ })).toBeInTheDocument();
  });

  it("вызывает onDiscard при клике на кнопку отмены", () => {
    const onSave = vi.fn();
    const onDiscard = vi.fn();

    render(<ContextualSaveBar visible={true} onSave={onSave} onDiscard={onDiscard} />);

    fireEvent.click(screen.getByRole("button", { name: "Отменить" }));
    expect(onDiscard).toHaveBeenCalledTimes(1);
    expect(onSave).not.toHaveBeenCalled();
  });

  it("вызывает onSave при клике на кнопку сохранения", () => {
    const onSave = vi.fn();
    const onDiscard = vi.fn();

    render(<ContextualSaveBar visible={true} onSave={onSave} onDiscard={onDiscard} />);

    fireEvent.click(screen.getByRole("button", { name: /Сохранить изменения/ }));
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onDiscard).not.toHaveBeenCalled();
  });

  it("срабатывает по хоткею Cmd+S и Ctrl+S (включая code=KeyS для RU раскладки)", () => {
    const onSave = vi.fn();
    const onDiscard = vi.fn();

    const { unmount } = render(
      <ContextualSaveBar visible={true} onSave={onSave} onDiscard={onDiscard} />,
    );

    // Meta+s (macOS EN)
    fireEvent.keyDown(window, { key: "s", metaKey: true });
    expect(onSave).toHaveBeenCalledTimes(1);

    // Ctrl+s (Linux/Win EN)
    fireEvent.keyDown(window, { key: "s", ctrlKey: true });
    expect(onSave).toHaveBeenCalledTimes(2);

    // Meta + code "KeyS" с русской раскладкой (key: "ы")
    fireEvent.keyDown(window, { key: "ы", code: "KeyS", metaKey: true });
    expect(onSave).toHaveBeenCalledTimes(3);

    unmount();
    // Проверка снятия листенера при размонтировании
    fireEvent.keyDown(window, { key: "s", metaKey: true });
    expect(onSave).toHaveBeenCalledTimes(3);
  });

  it("блокирует сохранение при disabled или loading", () => {
    const onSave = vi.fn();
    const onDiscard = vi.fn();

    const { rerender } = render(
      <ContextualSaveBar visible={true} disabled={true} onSave={onSave} onDiscard={onDiscard} />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Сохранить изменения/ }));
    fireEvent.keyDown(window, { key: "s", metaKey: true });
    expect(onSave).not.toHaveBeenCalled();

    rerender(
      <ContextualSaveBar visible={true} loading={true} onSave={onSave} onDiscard={onDiscard} />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Сохранить изменения/ }));
    fireEvent.keyDown(window, { key: "s", metaKey: true });
    expect(onSave).not.toHaveBeenCalled();
  });

  it("живой регион статуса есть и при скрытом баре — скринридер слышит появление изменений", () => {
    const { rerender } = render(
      <ContextualSaveBar visible={false} onSave={vi.fn()} onDiscard={vi.fn()} />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("");
    rerender(<ContextualSaveBar visible onSave={vi.fn()} onDiscard={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent("Есть несохранённые изменения");
  });

  it("два бара на экране: ⌘S сохраняет только форму с фокусом", () => {
    const first = vi.fn();
    const second = vi.fn();
    render(
      <>
        <form>
          <ContextualSaveBar visible onSave={first} onDiscard={vi.fn()} />
          <input aria-label="Имя" />
        </form>
        <form>
          <ContextualSaveBar visible onSave={second} onDiscard={vi.fn()} />
          <input aria-label="Заместитель" />
        </form>
      </>,
    );
    screen.getByRole("textbox", { name: "Заместитель" }).focus();
    fireEvent.keyDown(window, { key: "s", ctrlKey: true });
    expect(second).toHaveBeenCalledOnce();
    expect(first).not.toHaveBeenCalled();
  });
});
