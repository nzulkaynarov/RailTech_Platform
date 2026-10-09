import { render, screen } from "@testing-library/react";
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
    expect(screen.getByText(/Клиент ·/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).toBeNull();
  });
});
