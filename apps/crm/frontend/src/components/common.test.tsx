import { fireEvent, render, screen } from "@testing-library/react";
import { App as AntApp } from "antd";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/http";
import { BooleanTag } from "./BooleanTag";
import { EmptyState } from "./EmptyState";
import { leadLinkText } from "../domain/entities";
import { EntityLink, LeadLink } from "./EntityLink";
import { PageBody } from "./PageBody";
import { PageHeader } from "./PageHeader";
import { PageState } from "./PageState";

const wrap = (node: ReactNode) =>
  render(
    <MemoryRouter>
      <AntApp>{node}</AntApp>
    </MemoryRouter>,
  );

const ok = { isLoading: false, isError: false, error: null, refetch: vi.fn() };

describe("EmptyState", () => {
  it("explains what is empty and offers the action", () => {
    const onClick = vi.fn();
    wrap(
      <EmptyState
        title="Документов пока нет"
        hint="Загрузите договор"
        action={{ label: "Загрузить", onClick }}
      />,
    );
    expect(screen.getByText("Документов пока нет")).toBeInTheDocument();
    expect(screen.getByText("Загрузите договор")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Загрузить" }));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("renders without hint and action", () => {
    wrap(<EmptyState title="Пусто" />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("BooleanTag", () => {
  it.each([
    [true, "Да"],
    [false, "Нет"],
    [null, "Нет"],
  ])("%s → %s", (value, text) => {
    wrap(<BooleanTag value={value} />);
    expect(screen.getByText(text)).toBeInTheDocument();
  });

  it("accepts custom labels", () => {
    wrap(<BooleanTag value yes="Подтверждён" />);
    expect(screen.getByText("Подтверждён")).toBeInTheDocument();
  });
});

describe("LeadLink", () => {
  it.each([
    [11, "Иван", "#11 · Иван"],
    [11, "", "#11 · —"],
    [11, null, "#11 · —"],
    [11, undefined, "#11"],
  ])("leadLinkText(%s, %j) → %s", (id, name, text) => {
    expect(leadLinkText(id, name)).toBe(text);
  });

  it("links to the lead card", () => {
    wrap(<LeadLink id={7} name="ООО Ромашка" />);
    expect(screen.getByRole("link", { name: "#7 · ООО Ромашка" })).toHaveAttribute(
      "href",
      "/leads/7",
    );
  });

  it("allows custom text", () => {
    wrap(<LeadLink id={7}>из лида</LeadLink>);
    expect(screen.getByRole("link", { name: "из лида" })).toHaveAttribute("href", "/leads/7");
  });

  it("keeps EntityLink labels", () => {
    wrap(<EntityLink type="client" id={5} />);
    expect(screen.getByRole("link")).toHaveAttribute("href", "/clients/5");
  });
});

describe("PageHeader / PageBody", () => {
  it("renders the page title as the only h1", () => {
    wrap(
      <PageBody>
        <PageHeader title="Лиды" back="/" />
        <div>content</div>
      </PageBody>,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Лиды" })).toBeInTheDocument();
    expect(screen.getAllByRole("heading")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Назад" })).toBeInTheDocument();
  });
});

describe("PageState", () => {
  it("shows the empty state instead of content", () => {
    wrap(
      <PageState query={ok} empty={{ title: "Заметок нет" }}>
        <div>content</div>
      </PageState>,
    );
    expect(screen.getByText("Заметок нет")).toBeInTheDocument();
    expect(screen.queryByText("content")).toBeNull();
  });

  it("shows content when empty is false", () => {
    wrap(
      <PageState query={ok} empty={false}>
        <div>content</div>
      </PageState>,
    );
    expect(screen.getByText("content")).toBeInTheDocument();
  });

  it("reports a secondary query error compactly with retry", () => {
    const refetch = vi.fn();
    const query = {
      ...ok,
      isError: true,
      error: new ApiError(500, "http_error", "HTTP 500"),
      refetch,
    };
    wrap(
      <PageState query={query} variant="section" empty={{ title: "Решений нет" }}>
        <div>content</div>
      </PageState>,
    );
    expect(screen.queryByText("Решений нет")).toBeNull();
    expect(screen.getByRole("alert")).toHaveTextContent("Не удалось загрузить данные");
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    expect(refetch).toHaveBeenCalledOnce();
  });

  it("gives full-page errors an h1", () => {
    const query = { ...ok, isError: true, error: new ApiError(403, "forbidden", "") };
    wrap(
      <PageState query={query}>
        <div>content</div>
      </PageState>,
    );
    expect(
      screen.getByRole("heading", { level: 1, name: "Нет доступа к этому разделу" }),
    ).toBeInTheDocument();
  });
});
