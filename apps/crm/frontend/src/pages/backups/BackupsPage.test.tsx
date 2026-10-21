/**
 * «Резервные копии» (ADR-0013, M5-CRM-01): источник статуса, копия по каждой базе, подсказка при
 * ошибке бакета RustFS; «Сделать сейчас» есть только у тома. Запросы подменены — без сервера.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { App as AntApp } from "antd";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BackupsOut } from "../../api/generated/model";
import { BackupsPage } from "./BackupsPage";

const volume: BackupsOut = {
  available: true,
  source: "volume",
  can_request: true,
  error: null,
  databases: [],
  last_success_at: new Date(Date.now() - 3 * 3600_000).toISOString(),
  stale: false,
  requested_at: null,
  daemon_alive: true,
  request_stuck: false,
  items: [{ name: "20261021T220000Z", at: "2026-10-21T22:00:00Z", size_bytes: 2048 }],
};

const bucket: BackupsOut = {
  ...volume,
  source: "rustfs",
  can_request: false,
  databases: [
    { name: "crm", last_success_at: volume.last_success_at },
    { name: "erp", last_success_at: volume.last_success_at },
  ],
};

let current: BackupsOut = volume;
const request = { mutateAsync: vi.fn(), isPending: false };

vi.mock("../../api/systemQueries", () => ({
  useBackups: () => ({
    data: current,
    isLoading: false,
    isError: false,
    error: null,
    isFetching: false,
    refetch: vi.fn(() => Promise.resolve()),
  }),
  useRequestBackup: () => request,
}));

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AntApp>
        <MemoryRouter>
          <BackupsPage />
        </MemoryRouter>
      </AntApp>
    </QueryClientProvider>,
  );
}

describe("BackupsPage", () => {
  beforeEach(() => {
    current = volume;
  });

  it("volume: shows the source and the «Сделать сейчас» button", () => {
    renderPage();
    expect(screen.getByRole("heading", { level: 1 })).toBeVisible();
    expect(screen.getByText("Том резервных копий на этом сервере")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Сделать сейчас" })).toBeEnabled();
    expect(screen.queryByText("Последняя копия по базам")).not.toBeInTheDocument();
  });

  it("RustFS: shows the source, every database and no request button", () => {
    current = bucket;
    renderPage();
    expect(screen.getByText(/Бакет «backups» в RustFS/)).toBeInTheDocument();
    expect(screen.getByText("crm")).toBeInTheDocument();
    expect(screen.getByText("erp")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Сделать сейчас" })).not.toBeInTheDocument();
    expect(screen.getByText(/infra\/deploy\/backup-now\.sh/)).toBeInTheDocument();
  });

  it("RustFS: no copy for a day says what to check on the database server", () => {
    current = { ...bucket, stale: true };
    renderPage();
    expect(screen.getByText(/Нет успешной копии за сутки/)).toBeInTheDocument();
    expect(screen.getByText(/docker logs rt-db-backup-1/)).toBeInTheDocument();
  });

  it("RustFS: bucket error explains what to do", () => {
    current = {
      ...bucket,
      available: false,
      error: "bucket_missing",
      databases: [],
      last_success_at: null,
      stale: true,
      items: [],
    };
    renderPage();
    expect(screen.getByText(/Бакет «backups» не найден в хранилище/)).toBeInTheDocument();
    expect(screen.getByText(/BACKUP_RUSTFS_/)).toBeInTheDocument();
  });
});
