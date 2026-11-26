import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderUi } from "../../../test/renderUi";
import { DocumentStatusTag } from "./status";

describe("DocumentStatusTag: исходящее письмо", () => {
  it("ушло адресату — «Отправлено»", () => {
    renderUi(<DocumentStatusTag kind="letter_out" status="sent" />);
    expect(screen.getByText("Отправлено")).toBeVisible();
  });

  it("EDS поставил sent при подписи, но письмо не ушло — одна метка «Не отправлено», без «Отправлено»", () => {
    renderUi(<DocumentStatusTag kind="letter_out" status="sent" undelivered />);
    expect(screen.getByText("Не отправлено")).toBeVisible();
    expect(screen.queryByText("Отправлено")).toBeNull();
  });
});
