import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderUi } from "../../test/renderUi";
import { SourceBanner } from "./SourceBanner";

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
});
