import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderUi } from "../../test/renderUi";
import { EmptyState } from "./EmptyState";
import { QueueList, type QueueItem } from "./QueueList";

const ITEMS: QueueItem[] = [
  {
    id: "1",
    badge: { tone: "red", label: "срок сегодня" },
    title: "Наложить резолюцию на письмо ВХ-104/26",
    caption: "АО «Демо-Транс» · заявка ЗВ-2026-104",
    to: "/eds/inbox?letter=%D0%92%D0%A5-104%2F26",
  },
  {
    id: "2",
    badge: { tone: "gold", label: "завтра" },
    title: "Одобрить КП-2026/118",
    to: "/eds/drafts",
  },
  {
    id: "3",
    badge: { tone: "purple", label: "служебка" },
    title: "Согласовать СЗ-2026/031",
    to: "/eds/approvals",
  },
];

describe("QueueList", () => {
  it("секция с заголовком, строки со словом срока, названием и подписью", () => {
    renderUi(<QueueList title="Что сделать сейчас" items={ITEMS} />);
    const section = screen.getByRole("region", { name: "Что сделать сейчас" });
    expect(within(section).getAllByRole("listitem")).toHaveLength(3);
    expect(within(section).getByText("срок сегодня")).toBeVisible();
    expect(within(section).getByText("АО «Демо-Транс» · заявка ЗВ-2026-104")).toBeVisible();
  });

  it("«Открыть» — настоящая ссылка с именем строки; primary только у самой срочной", () => {
    renderUi(<QueueList title="Что сделать сейчас" items={ITEMS} />);
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(3);
    expect(links[0]).toHaveAccessibleName("Открыть: Наложить резолюцию на письмо ВХ-104/26");
    expect(links[0]).toHaveAttribute("href", ITEMS[0]?.to);
    expect(links[0]).toHaveClass("ant-btn-primary");
    expect(links[1]).not.toHaveClass("ant-btn-primary");
    expect(links[2]).not.toHaveClass("ant-btn-primary");
  });

  it("без строк — пустое состояние словами", () => {
    renderUi(
      <QueueList
        title="Что сделать сейчас"
        items={[]}
        empty={
          <EmptyState
            level={3}
            title="Решений от вас пока не требуется"
            text="Новые письма приходят из CRM."
          />
        }
      />,
    );
    expect(screen.getByText("Решений от вас пока не требуется")).toBeVisible();
    expect(screen.queryByRole("list")).toBeNull();
  });
});
