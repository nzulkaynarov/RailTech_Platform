import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { useLocation } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderUi } from "../../../test/renderUi";

/* pdf.js в jsdom не работает (холст, рабочий поток): подменяем его минимальным двойником с теми же событиями. */
const calls = vi.hoisted(() => ({
  scaleValues: [] as string[],
  found: [] as Array<Record<string, unknown>>,
  pageSets: [] as number[],
  bus: null as null | { emit: (name: string, payload: unknown) => void },
}));

vi.mock("pdfjs-dist/build/pdf.worker.min.mjs?url", () => ({ default: "worker.js" }));
vi.mock("pdfjs-dist", () => ({
  AnnotationMode: { DISABLE: 0 },
  GlobalWorkerOptions: {},
  getDocument: () => ({
    promise: Promise.resolve({ numPages: 3, getPage: () => Promise.reject(new Error("no")) }),
    destroy: () => Promise.resolve(),
  }),
}));
vi.mock("pdfjs-dist/web/pdf_viewer.css", () => ({}));
vi.mock("pdfjs-dist/web/pdf_viewer.mjs", () => {
  class EventBus {
    handlers = new Map<string, Array<(payload: never) => void>>();
    on(name: string, handler: (payload: never) => void) {
      this.handlers.set(name, [...(this.handlers.get(name) ?? []), handler]);
    }
    emit(name: string, payload: unknown) {
      (this.handlers.get(name) ?? []).forEach((handler) => {
        handler(payload as never);
      });
    }
    dispatch(name: string, payload: Record<string, unknown>) {
      if (name === "find") calls.found.push(payload);
    }
  }
  class PDFViewer {
    pagesCount = 3;
    private page = 1;
    constructor(options: { eventBus: EventBus }) {
      calls.bus = options.eventBus;
    }
    set currentScaleValue(value: string) {
      calls.scaleValues.push(value);
    }
    get currentPageNumber() {
      return this.page;
    }
    set currentPageNumber(value: number) {
      this.page = value;
      calls.pageSets.push(value);
      calls.bus?.emit("pagechanging", { pageNumber: value });
    }
    setDocument() {
      queueMicrotask(() => {
        calls.bus?.emit("pagesinit", {});
      });
    }
    increaseScale() {
      calls.bus?.emit("scalechanging", { scale: 1.1 });
    }
    decreaseScale() {
      calls.bus?.emit("scalechanging", { scale: 0.9 });
    }
  }
  class PDFLinkService {
    setViewer() {}
    setDocument() {}
  }
  // eslint-disable-next-line @typescript-eslint/no-extraneous-class
  class PDFFindController {}
  return { EventBus, PDFViewer, PDFLinkService, PDFFindController };
});

const { default: DocumentViewer } = await import("./DocumentViewer");

function Where() {
  const location = useLocation();
  return <output data-testid="where">{location.pathname + location.search}</output>;
}

const bytes = new ArrayBuffer(8);

function show(route = "/docs") {
  return renderUi(
    <>
      <Where />
      <DocumentViewer data={bytes} name="Договор" />
    </>,
    { route },
  );
}

describe("DocumentViewer", () => {
  beforeEach(() => {
    calls.scaleValues.length = 0;
    calls.found.length = 0;
    calls.pageSets.length = 0;
  });

  it("panel: one toolbar with fit, zoom, page, search, download and full screen", async () => {
    show();
    expect(await screen.findByRole("button", { name: "Скачать" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "На весь экран" })).toBeInTheDocument();
    expect(screen.getByText("из 3")).toBeInTheDocument();
    expect(screen.getByText("100 %", { selector: "span.pf-dv-percent" })).toBeInTheDocument();
    expect(calls.scaleValues).toContain("page-width");
    fireEvent.click(screen.getByRole("button", { name: "Увеличить" }));
    expect(screen.getByText("110 %")).toBeInTheDocument();
  });

  it("search: sends the query and shows the matches count", async () => {
    show();
    const input = await screen.findByRole("textbox", { name: "Поиск по тексту" });
    await waitFor(() => {
      expect(input).toBeEnabled();
    });
    fireEvent.change(input, { target: { value: "срок" } });
    expect(calls.found.at(-1)).toMatchObject({ query: "срок", highlightAll: true });
    act(() => {
      calls.bus?.emit("updatefindmatchescount", { matchesCount: { current: 1, total: 3 } });
    });
    expect(screen.getByText("1 из 3")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Следующее совпадение" }));
    expect(calls.found.at(-1)).toMatchObject({ type: "again", findPrevious: false });
  });

  it("full screen: address ?view=full&page=N, Esc collapses and focus returns to the button", async () => {
    show();
    const button = await screen.findByRole("button", { name: "На весь экран" });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Скачать" })).toBeEnabled();
    });
    button.focus();
    fireEvent.click(button);
    const layer = await screen.findByRole("dialog");
    expect(layer).toHaveAccessibleName("Договор");
    expect(screen.getByTestId("where")).toHaveTextContent("/docs?view=full&page=1");
    expect(await screen.findByTestId("dv-collapse")).toBeInTheDocument();
    fireEvent.keyDown(layer, { key: "Escape", code: "Escape", keyCode: 27 });
    // слой закрыт: адрес вернулся на страницу под ним (сам узел уходит после анимации antd, в jsdom она не кончается)
    expect(screen.getByTestId("where")).toHaveTextContent("/docs");
    expect(screen.getByTestId("where")).not.toHaveTextContent("view=full");
    await waitFor(() => {
      expect(button).toHaveFocus();
    });
  });

  it("the address opens the layer on the page from the link", async () => {
    show("/docs?view=full&page=2");
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    await waitFor(() => {
      expect(calls.pageSets).toContain(2);
    });
  });

  it("keys: plus zooms, 0 fits the width, arrows turn pages", async () => {
    show();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Скачать" })).toBeEnabled();
    });
    const region = screen.getByRole("region", { name: "Страницы файла «Договор»" });
    fireEvent.keyDown(region, { key: "+" });
    expect(screen.getByText("110 %")).toBeInTheDocument();
    fireEvent.keyDown(region, { key: "ArrowRight" });
    expect(calls.pageSets.at(-1)).toBe(2);
    fireEvent.keyDown(region, { key: "0" });
    expect(calls.scaleValues.at(-1)).toBe("page-width");
  });

  it("about: the full layer shows the «О документе» column, the panel does not", async () => {
    renderUi(<DocumentViewer data={bytes} name="Договор" about={<p>ДОГ-2026/111</p>} />, {
      route: "/docs?view=full&page=1",
    });
    const aside = await screen.findByRole("complementary", { name: "О документе" });
    expect(aside).toHaveTextContent("ДОГ-2026/111");
    expect(screen.getAllByText("ДОГ-2026/111")).toHaveLength(1);
  });

  it("sniffType: shows PDF and images by their first bytes, Word and Excel are left to download", async () => {
    const { sniffType } = await import("./sniffType");
    const of = (...codes: number[]) => new Uint8Array(codes).buffer;
    expect(sniffType(of(0x25, 0x50, 0x44, 0x46, 0x2d))).toBe("application/pdf");
    expect(sniffType(of(0x89, 0x50, 0x4e, 0x47))).toBe("image/png");
    expect(sniffType(of(0xff, 0xd8, 0xff))).toBe("image/jpeg");
    expect(sniffType(of(0x50, 0x4b, 0x03, 0x04))).toBeNull();
  });
});
