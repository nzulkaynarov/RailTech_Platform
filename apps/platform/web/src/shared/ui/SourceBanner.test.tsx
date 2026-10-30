import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MemoryRouter } from "react-router";

import { AppProviders } from "../../app/providers";
import type { Sources } from "../api/generated/model";
import { renderUi } from "../../test/renderUi";
import { SOURCE_SETTLE_MS, SourceBanner } from "./SourceBanner";

describe("SourceBanner", () => {
  it("ERP не отвечает — плашка role=status со словами", () => {
    renderUi(<SourceBanner sources={{ crm: "ok", erp: "unavailable" }} />);
    expect(screen.getByRole("status")).toHaveTextContent("ERP не отвечает, данные неполные");
  });

  it("CRM не отвечает и оба не отвечают", () => {
    const { unmount } = renderUi(<SourceBanner sources={{ crm: "unavailable", erp: "ok" }} />);
    expect(screen.getByRole("status")).toHaveTextContent("CRM не отвечает, данные неполные");
    unmount();
    renderUi(<SourceBanner sources={{ crm: "unavailable", erp: "unavailable" }} />);
    expect(screen.getByRole("status")).toHaveTextContent("CRM и ERP не отвечают, данные неполные");
  });

  it("всё в порядке или нет доступа к бэкенду — плашки нет", () => {
    const { container } = renderUi(
      <>
        <SourceBanner sources={{ crm: "ok", erp: "ok" }} />
        <SourceBanner sources={{ crm: "ok", erp: "not_applicable" }} />
        <SourceBanner sources={undefined} />
      </>,
    );
    expect(container.querySelector("[role=status]")).toBeNull();
  });

  it("«Повторить» только с обработчиком", () => {
    const onRetry = vi.fn();
    renderUi(<SourceBanner sources={{ crm: "ok", erp: "unavailable" }} onRetry={onRetry} />);
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("нет кнопки без обработчика", () => {
    renderUi(<SourceBanner sources={{ crm: "ok", erp: "unavailable" }} />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("мигание источника при опросе не двигает список: смена — только после 3 с (UX-1c, S10)", () => {
    vi.useFakeTimers();
    try {
      // Тот же экземпляр плашки между ответами опроса: обёртка та же, меняются только `sources`
      const tree = (sources: Sources | undefined) => (
        <AppProviders>
          <MemoryRouter>
            <SourceBanner sources={sources} />
          </MemoryRouter>
        </AppProviders>
      );
      const { rerender: rerenderTree } = render(tree({ crm: "ok", erp: "ok" }));
      const rerender = (sources: Sources | undefined) => {
        rerenderTree(tree(sources));
      };
      expect(screen.queryByRole("status")).toBeNull();
      rerender({ crm: "ok", erp: "unavailable" });
      act(() => {
        vi.advanceTimersByTime(SOURCE_SETTLE_MS - 100);
      });
      expect(screen.queryByRole("status")).toBeNull();
      // Источник снова ответил до истечения — плашки так и не было
      rerender({ crm: "ok", erp: "ok" });
      act(() => {
        vi.advanceTimersByTime(SOURCE_SETTLE_MS);
      });
      expect(screen.queryByRole("status")).toBeNull();
      // Упал надолго — плашка через 3 с; перезапрос без ответа (`undefined`) её не снимает
      rerender({ crm: "ok", erp: "unavailable" });
      act(() => {
        vi.advanceTimersByTime(SOURCE_SETTLE_MS);
      });
      expect(screen.getByRole("status")).toHaveTextContent("ERP не отвечает");
      rerender(undefined);
      act(() => {
        vi.advanceTimersByTime(SOURCE_SETTLE_MS);
      });
      expect(screen.getByRole("status")).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});
