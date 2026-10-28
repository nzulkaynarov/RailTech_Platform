import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Markdown } from "./Markdown";

afterEach(cleanup);

/** Статьи компании пишет человек: рендер не должен исполнять ни HTML, ни скрипты, ни опасные ссылки (W18A-P5). */
describe("Markdown: безопасный показ чужого текста", () => {
  const hostile = [
    "<script>window.__xss = 1</script>",
    '<img src=x onerror="window.__xss = 2">',
    '<a href="javascript:window.__xss = 3">нажми</a>',
    "[ссылка](javascript:window.__xss=4)",
    "![картинка](https://evil.example/pixel.png)",
    '<iframe src="https://evil.example"></iframe>',
    '**жирный <b onmouseover="window.__xss=5">тег</b>**',
    "`<script>x</script>`",
    '## <svg onload="window.__xss=6"> заголовок',
    "- <style>body{display:none}</style>",
  ].join("\n\n");

  it("весь HTML остаётся текстом: ни одного script, img, a, iframe, svg, style в дереве", () => {
    const { container } = render(<Markdown source={hostile} />);
    for (const tag of ["script", "img", "a", "iframe", "svg", "style", "b"]) {
      expect(container.querySelector(tag), tag).toBeNull();
    }
    const attributes = [...container.querySelectorAll("*")].flatMap((el) => el.getAttributeNames());
    expect(attributes.filter((name) => name !== "class")).toEqual([]);
    expect(container.querySelectorAll("[href], [src]")).toHaveLength(0);
    expect((window as unknown as { __xss?: number }).__xss).toBeUndefined();
  });

  it("и сами строки доходят до читателя как текст", () => {
    render(<Markdown source={hostile} />);
    expect(screen.getByText("<script>window.__xss = 1</script>")).toBeInTheDocument();
    expect(screen.getByText(/javascript:window\.__xss = 3/)).toBeInTheDocument();
    expect(screen.getByText("[ссылка](javascript:window.__xss=4)")).toBeInTheDocument();
  });

  it("поддерживаемая разметка работает: заголовки, списки, жирный, код", () => {
    const { container } = render(
      <Markdown source={"## Шаги\n\n1. один\n2. два\n\n- пункт\n\nтекст **важно** и `код`"} />,
    );
    expect(screen.getByRole("heading", { level: 3, name: "Шаги" })).toBeInTheDocument();
    expect(container.querySelectorAll("ol > li")).toHaveLength(2);
    expect(container.querySelectorAll("ul > li")).toHaveLength(1);
    expect(container.querySelector("strong")?.textContent).toBe("важно");
    expect(container.querySelector("code")?.textContent).toBe("код");
  });
});
