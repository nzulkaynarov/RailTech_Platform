/* eslint-disable no-restricted-syntax -- проба с литеральными ключами: проверяется только предикат по адресу запроса */
import { QueryClient, useQuery } from "@tanstack/react-query";
import { act, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import i18n from "../shared/i18n";
import { AppProviders } from "./providers";

let queueCalls = 0;
let otherCalls = 0;

function Probe() {
  useQuery({
    queryKey: ["/api/v1/queue", {}],
    queryFn: () => Promise.resolve({ n: ++queueCalls }),
    staleTime: Infinity,
  });
  useQuery({
    queryKey: ["/api/v1/clients", {}],
    queryFn: () => Promise.resolve({ n: ++otherCalls }),
    staleTime: Infinity,
  });
  return null;
}

describe("AppProviders: язык и очередь «Главной»", () => {
  afterEach(async () => {
    await i18n.changeLanguage("ru");
  });

  it("смена языка перечитывает очередь и ленту, а остальные запросы не трогает (СЦ-7, N1)", async () => {
    queueCalls = 0;
    otherCalls = 0;
    const client = new QueryClient();
    render(
      <AppProviders queryClient={client}>
        <Probe />
      </AppProviders>,
    );
    await waitFor(() => {
      expect(queueCalls).toBe(1);
    });
    await act(async () => {
      await i18n.changeLanguage("uz");
    });
    await waitFor(() => {
      expect(queueCalls).toBe(2);
    });
    expect(otherCalls).toBe(1);
  });
});
