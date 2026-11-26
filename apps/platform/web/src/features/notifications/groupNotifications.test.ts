import { describe, expect, it } from "vitest";

import type { Notification } from "../../shared/api/generated/model";
import { groupNotifications } from "./groupNotifications";

const quote = { kind: "quote", number: "RFQ-1126-02", path: "/eds/drafts/RFQ-1126-02" } as const;
const note = (
  id: number,
  at: string,
  read: boolean,
  object?: Notification["object"],
): Notification => ({
  id: `erp:${String(id)}`,
  tab: "decisions",
  title: `n${String(id)}`,
  created_at: at,
  read,
  needs_action: !read,
  ...(object ? { object } : {}),
});

describe("groupNotifications", () => {
  it("склеивает события одного объекта и считает непрочитанные", () => {
    const groups = groupNotifications([
      note(1, "2026-11-26T10:00:00Z", false, quote),
      note(2, "2026-11-26T11:00:00Z", false, quote),
      note(3, "2026-11-26T12:00:00Z", true, quote),
    ]);
    expect(groups).toHaveLength(1);
    expect(groups[0]?.items).toHaveLength(3);
    expect(groups[0]?.unread).toBe(2);
    expect(groups[0]?.head.id).toBe("erp:3");
  });

  it("ставит группы с непрочитанным выше прочитанных, даже если прочитанные новее", () => {
    const groups = groupNotifications([
      note(1, "2026-11-26T09:00:00Z", false),
      note(2, "2026-11-26T12:00:00Z", true),
    ]);
    expect(groups.map((g) => g.head.id)).toEqual(["erp:1", "erp:2"]);
  });

  it("уведомления без объекта не склеиваются", () => {
    expect(
      groupNotifications([
        note(1, "2026-11-26T09:00:00Z", false),
        note(2, "2026-11-26T10:00:00Z", false),
      ]),
    ).toHaveLength(2);
  });
});
