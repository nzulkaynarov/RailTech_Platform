import tseslint from "typescript-eslint";
import { RuleTester } from "eslint";
import { join } from "node:path";
import { afterAll, describe, expect, it } from "vitest";

import {
  ALL_KINDS,
  CSS_KIND,
  detectCss,
  detectTs,
  loadAllowlist,
  loadBaseline,
  scanTree,
  WEB_ROOT,
} from "../../ui-guards/detect.mjs";
import plugin from "../../ui-guards/eslint-plugin.mjs";

// RuleTester вызывает эти функции, если они заданы; в типах ESLint поля afterAll нет — задаём через Object.assign.
Object.assign(RuleTester, { afterAll, describe, it });

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

describe("ui-guards: hostile inputs", () => {
  const kinds = (source: string) => detectTs(source).map((hit) => hit.kind);

  it("catches deep imports antd/es/<x> and antd/lib/<x>", () => {
    expect(
      kinds(
        `import Drawer from "antd/es/drawer";
         import { default as T } from "antd/lib/table";
         import Spin from "antd/es/spin/index";
         import Popconfirm from "antd/es/popconfirm";
         import Modal from "antd/es/modal";
         import Button from "antd/es/button";`,
      ),
    ).toEqual(["drawer", "table", "spin", "confirm", "modal"]);
  });

  it("catches namespace and default imports of antd, in JSX and in destructuring", () => {
    expect(
      kinds(
        `import * as antd from "antd";
         import A from "antd";
         const x = <antd.Table />; const y = <antd.Spin />;
         const z = A.Drawer; const { Popconfirm: P, Button } = antd;
         const ok = antd.Button;`,
      ),
    ).toEqual(["table", "spin", "drawer", "confirm"]);
  });

  it("catches confirm on a renamed modal from App.useApp() and Modal.useModal()", () => {
    expect(
      kinds(
        `const { modal: dialogs } = App.useApp();
         dialogs.confirm({});
         const [m] = Modal.useModal();
         m.confirm({});
         const app = App.useApp();
         app.modal.confirm({});
         const q = app.modal; q.confirm({});
         App.useApp().modal.confirm({});
         other.confirm({});`,
      ),
    ).toEqual(["confirm", "confirm", "confirm", "confirm", "confirm"]);
  });

  it("catches module CSS that restyles the shared frame", () => {
    const css = `.pf-x .pf-dt-table [data-selected] { background: red }
      .pf-y .pf-fixed-table { color: red }
      .pf-z tr[data-selected="true"] > td { color: red }
      .pf-dt-tables-list { color: red }`;
    expect(detectCss(css).map((hit) => hit.line)).toEqual([1, 2, 3]);
  });
});

describe("ui-guards: ESLint rule rt-ui/no-raw-ui", () => {
  const tester = new RuleTester({
    languageOptions: {
      parser: tseslint.parser,
      ecmaVersion: 2022,
      sourceType: "module",
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
  });
  const rule = plugin.rules["no-raw-ui"];
  const inModule = (path: string) => join(WEB_ROOT, path);
  const listed = "src/modules/admin/signing/AuthorityDrawer.tsx";
  const listedSource = (loadAllowlist().drawer ?? []).find((entry) => entry.path === listed);
  const drawer = 'import { Drawer } from "antd";\n';

  it("the listed file used below is in the allow-list with one violation", () => {
    expect(listedSource?.count).toBe(1);
  });

  tester.run("no-raw-ui", rule, {
    valid: [
      // a file from the allow-list keeps its existing violation
      { code: drawer, filename: inModule(listed) },
      // tests are skipped
      { code: drawer, filename: inModule("src/modules/admin/New.test.tsx") },
      // shared/ui is where the shared parts live
      { code: drawer, filename: inModule("src/shared/ui/Sheet/Sheet.tsx") },
      // shared components are fine anywhere
      {
        code: 'import { RegistryTable } from "../../shared/ui/RegistryTable";',
        filename: inModule("src/modules/admin/New.tsx"),
      },
    ],
    invalid: [
      { code: drawer, filename: inModule("src/modules/admin/New.tsx"), errors: 1 },
      { code: drawer, filename: inModule("src/features/help/New.tsx"), errors: 1 },
      { code: drawer, filename: inModule("src/entities/x/New.tsx"), errors: 1 },
      // one more Drawer in an allow-listed file is new
      {
        code: drawer + drawer.replace("Drawer", "Drawer as D2"),
        filename: inModule(listed),
        errors: 1,
      },
      {
        code: 'import Drawer from "antd/es/drawer";',
        filename: inModule("src/features/help/New.tsx"),
        errors: 1,
      },
      {
        code: 'import * as antd from "antd"; const a = <antd.Table />;',
        filename: inModule("src/entities/x/New.tsx"),
        errors: 1,
      },
      {
        code: "const { modal: dialogs } = App.useApp(); dialogs.confirm({});",
        filename: inModule("src/features/help/New.tsx"),
        errors: 1,
      },
    ],
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

  it("each listed file has exactly the stored number of violations (a new one in a listed file is red)", () => {
    const wrong: string[] = [];
    for (const kind of ALL_KINDS) {
      for (const entry of allow[kind] ?? []) {
        const actual = found.get(kind)?.get(entry.path) ?? 0;
        if (actual !== entry.count)
          wrong.push(
            `${kind}: ${entry.path} has ${String(actual)}, list says ${String(entry.count)}`,
          );
      }
    }
    expect(wrong, "lower the count in ui-guards/allowlist.json, never raise it").toEqual([]);
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
