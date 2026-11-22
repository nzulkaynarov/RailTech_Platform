import { describe, expect, it } from "vitest";

import {
  ALL_KINDS,
  CSS_KIND,
  detectCss,
  detectTs,
  loadAllowlist,
  loadBaseline,
  scanTree,
} from "../../ui-guards/detect.mjs";

/**
 * ЕВ-1а: «новых нарушений нет, список сокращается». Сырые Drawer / Modal / Popconfirm / Table / Spin, `<table>`, свои
 * правила таблицы в CSS модуля — только из `ui-guards/allowlist.json` (путь и причина). ESLint (`rt-ui/no-raw-ui`) ловит
 * новое в TS; эти проверки — CSS, устаревшие записи и счёт, который только уменьшается (`ui-guards/baseline.json`).
 */
describe("ui-guards: detector", () => {
  it("finds a raw Drawer, Popconfirm, Table, Spin and Modal imported from antd", () => {
    const hits = detectTs(
      'import { Drawer, Popconfirm, Table, Spin, Modal as M, Button } from "antd";',
    );
    expect(hits.map((hit) => hit.kind).sort()).toEqual([
      "confirm",
      "drawer",
      "modal",
      "spin",
      "table",
    ]);
  });

  it("finds <table> and modal.confirm() but not names that only look alike", () => {
    const hits = detectTs(
      `const a = <table><tbody/></table>;
       modal.confirm({ title: "x" });
       Modal.confirm({});
       const b = <DataTable />;
       confirmAction.confirm();`,
    );
    expect(hits.map((hit) => hit.kind)).toEqual(["table", "confirm", "confirm"]);
  });

  it("finds table styling in module CSS but not table-like class names", () => {
    const css = `
      /* .x th { color: red } */
      .pf-foo-table { color: red }
      .pf-foo .pf-bar-th { color: red }
      .pf-foo th, .pf-bar { color: red }
      .ant-table-wrapper .ant-table-tbody > tr.x > td { color: red }
      @media (max-width: 600px) { .pf-x { color: red } table.pf-y td { color: red } }
      a[href$="td"] { color: red }`;
    expect(detectCss(css).map((hit) => hit.line)).toEqual([5, 6, 7]);
  });
});

describe("ui-guards: allow-list only shrinks", () => {
  const allow = loadAllowlist();
  const baseline = loadBaseline();
  const found = scanTree();

  it("every violation in module code is in the allow-list (new ones are forbidden)", () => {
    const fresh: string[] = [];
    for (const kind of ALL_KINDS) {
      const listed = new Set((allow[kind] ?? []).map((entry) => entry.path));
      for (const path of found.get(kind)?.keys() ?? []) {
        if (!listed.has(path)) fresh.push(`${kind}: ${path}`);
      }
    }
    expect(
      fresh,
      "new violation — use the shared component instead of adding it to the allow-list",
    ).toEqual([]);
  });

  it("every allow-list entry is still a violation and has a reason (fixed ones are removed)", () => {
    const stale: string[] = [];
    const noReason: string[] = [];
    for (const kind of ALL_KINDS) {
      for (const entry of allow[kind] ?? []) {
        if (!found.get(kind)?.has(entry.path)) stale.push(`${kind}: ${entry.path}`);
        if (entry.reason.trim().length < 20) noReason.push(`${kind}: ${entry.path}`);
      }
    }
    expect(stale, "fixed — remove from ui-guards/allowlist.json and lower baseline.json").toEqual(
      [],
    );
    expect(noReason).toEqual([]);
  });

  it("the stored count equals the allow-list: it can only go down, never up", () => {
    for (const kind of ALL_KINDS) {
      const count = (allow[kind] ?? []).length;
      const stored = baseline[kind] ?? 0;
      expect(count, `${kind}: allow-list grew over ui-guards/baseline.json`).toBeLessThanOrEqual(
        stored,
      );
      expect(count, `${kind}: lower the number in ui-guards/baseline.json`).toBe(stored);
    }
    expect(Object.keys(baseline).sort()).toEqual([...ALL_KINDS].sort());
    expect(CSS_KIND).toBe("css-table");
  });
});
