import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { App as AntApp } from "antd";
import { describe, expect, it, vi } from "vitest";

import type { UserOut } from "../../api/generated/model";
import { EditUserDialog } from "./UserDialogs";

const user = {
  id: 4,
  email: "m@railtech.uz",
  full_name: "Менеджер",
  roles: ["manager"],
  is_active: true,
  tg_user_id: null,
} as unknown as UserOut;

const renderDialog = (transferRequired: number | null) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, enabled: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AntApp>
        <EditUserDialog
          user={user}
          saving={false}
          transferRequired={transferRequired}
          onCancel={vi.fn()}
          onSubmit={vi.fn()}
        />
      </AntApp>
    </QueryClientProvider>,
  );
};

describe("EditUserDialog — transfer picker", () => {
  it("is hidden while the backend has not asked for a transfer", () => {
    renderDialog(null);
    expect(screen.queryByText("Передать лидов и сделки коллеге")).toBeNull();
  });

  it("appears with the lead count after user_has_active_leads", () => {
    renderDialog(3);
    expect(screen.getAllByText("Передать лидов и сделки коллеге").length).toBeGreaterThan(0);
    expect(screen.getByText(/ведёт лидов в работе \(3\)/)).toBeInTheDocument();
    expect(screen.getAllByRole("combobox")).toHaveLength(2); // роли и коллега
  });
});
