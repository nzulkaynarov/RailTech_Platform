import { screen, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "../../../test/server";
import { renderUi } from "../../../test/renderUi";
import { SigningList } from "./SigningList";

describe("«Ждут вашей подписи» (план 0.7, FR-30)", () => {
  it("сумма — с разрядами и словом валюты, а не «604800000.00 UZS»", async () => {
    server.use(
      http.get("*/api/v1/eds/signing-approvals", () =>
        HttpResponse.json({
          items: [
            {
              id: "a-1",
              kind: "act",
              number: "АКТ-2026/001",
              title: "Акт АКТ-2026/001",
              amount: "604800000.00",
              currency: "UZS",
              created_at: "2026-11-14T08:00:00Z",
            },
          ],
        }),
      ),
    );
    renderUi(<SigningList />);
    const list = await screen.findByRole("list", { name: "Ждут вашей подписи" });
    expect(within(list).getByText("Акт АКТ-2026/001")).toBeVisible();
    expect(within(list).queryByText(/604800000\.00/)).toBeNull();
    expect(within(list).getByText(/604\s800\s000\sсум/)).toBeVisible();
  });
});
