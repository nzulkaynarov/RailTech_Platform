import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { MessageOut } from "../api/generated/model";
import { ChatThread } from "./ChatThread";

const message = (id: number, role: string, text: string): MessageOut => ({
  id,
  role,
  text,
  attachments: [],
  sent_by_user_id: null,
  created_at: "2026-10-08T10:00:00Z",
  meta: {},
});

describe("ChatThread", () => {
  it("renders messages with role labels and hides reply when not allowed", () => {
    render(
      <ChatThread
        messages={[
          message(1, "lead", "Сколько стоит?"),
          message(2, "bot", "Расчёт делает менеджер"),
        ]}
        canReply={false}
        sending={false}
        onSend={vi.fn()}
      />,
    );
    expect(screen.getByText("Сколько стоит?")).toBeInTheDocument();
    expect(screen.getByText(/Лид ·/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("is a focusable, labelled log with lead messages in the lead's language", () => {
    render(
      <ChatThread
        messages={[message(1, "lead", "Narxi qancha?"), message(2, "bot", "Javob")]}
        canReply={false}
        sending={false}
        language="uz"
        onSend={vi.fn()}
      />,
    );
    const log = screen.getByRole("log", { name: "Переписка" });
    expect(log).toHaveAttribute("tabindex", "0");
    expect(screen.getByText("Narxi qancha?")).toHaveAttribute("lang", "uz");
    expect(screen.getByText("Javob")).not.toHaveAttribute("lang");
  });

  it("signs a manager reply with the colleague's name, falls back to the role", () => {
    const names = new Map([[7, "Елена"]]);
    render(
      <ChatThread
        messages={[
          { ...message(1, "manager", "Здравствуйте!"), sent_by_user_id: 7 },
          { ...message(2, "manager", "Уволенный коллега"), sent_by_user_id: 9 },
          message(3, "bot", "Бот ответил"),
        ]}
        canReply={false}
        sending={false}
        authorName={(id) => names.get(id)}
        onSend={vi.fn()}
      />,
    );
    expect(screen.getByText(/^Елена ·/)).toBeInTheDocument();
    expect(screen.getByText(/^Менеджер ·/)).toBeInTheDocument();
    expect(screen.getByText(/^Бот ·/)).toBeInTheDocument();
  });

  it("explains an empty thread", () => {
    render(<ChatThread messages={[]} canReply={false} sending={false} onSend={vi.fn()} />);
    expect(screen.getByText("Сообщений пока нет")).toBeInTheDocument();
  });

  it("sends on Enter on desktop and keeps Shift+Enter for a new line", () => {
    // десктоп: все брейкпоинты по ширине выполняются, указатель — мышь
    const media = vi.spyOn(window, "matchMedia").mockImplementation(
      (query: string) =>
        ({
          matches: query.includes("min-width"),
          media: query,
          onchange: null,
          addListener: () => undefined,
          removeListener: () => undefined,
          addEventListener: () => undefined,
          removeEventListener: () => undefined,
          dispatchEvent: () => false,
        }) as MediaQueryList,
    );
    const onSend = vi.fn().mockResolvedValue(undefined);
    render(<ChatThread messages={[]} canReply sending={false} onSend={onSend} />);
    const box = screen.getByRole("textbox", { name: "Ответ лиду" });
    fireEvent.change(box, { target: { value: "Здравствуйте" } });
    fireEvent.keyDown(box, { key: "Enter", shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith("Здравствуйте");
    expect(screen.getByText(/Shift\+Enter/)).toBeInTheDocument();
    media.mockRestore();
  });

  it("keeps Enter as a new line on a phone, sending only by the button", () => {
    const onSend = vi.fn().mockResolvedValue(undefined);
    render(<ChatThread messages={[]} canReply sending={false} onSend={onSend} />);
    const box = screen.getByRole("textbox", { name: "Ответ лиду" });
    fireEvent.change(box, { target: { value: "Строка" } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onSend).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Отправить" }));
    expect(onSend).toHaveBeenCalledWith("Строка");
  });
});
