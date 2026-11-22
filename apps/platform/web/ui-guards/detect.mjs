// Detector of "raw" UI in module code (ЕВ-1а). One source of truth for the ESLint rule (`eslint-plugin.mjs`), the
// allow-list tests (`src/test/uiGuards.test.ts`) and the coverage number (`coverage.mjs`).
import { readFileSync, readdirSync } from "node:fs";
import { join, relative, sep } from "node:path";
import ts from "typescript";

export const WEB_ROOT = join(import.meta.dirname, "..");
/** Module code: everything a screen is built from. `shared/ui` and `app` are where the shared parts live. */
export const GUARDED_DIRS = ["src/modules", "src/features", "src/entities"];

/** Kinds of TS violations and the message the ESLint rule gives for each. */
export const KINDS = {
  drawer:
    "Raw AntD Drawer is forbidden in module code: use the shared panel (FormSheet / Sheet) — widths 480 or 640 only (ui-standard §6).",
  confirm:
    "Popconfirm / modal.confirm are forbidden in module code: one confirmation — useConfirmAction (shared/ui) (ui-standard §6).",
  table:
    "Raw AntD Table / <table> is forbidden in module code: RegistryTable (shared/ui) gives the card, header band, rows, selection, pager and states (ui-standard §7).",
  spin: "Spin is forbidden in module code: loading is a skeleton shaped like the content — ListSkeleton / Skeleton (ui-standard §7).",
  modal:
    "Raw AntD Modal is forbidden in module code: Dialog (448, 1–3 fields) or FormSheet (ui-standard §6).",
};
/** CSS kind: table styling in a module stylesheet. */
export const CSS_KIND = "css-table";
export const CSS_MESSAGE =
  "Table styling in module CSS is forbidden: the look of a list is given by DataTable / RegistryTable (shared/ui).";
export const ALL_KINDS = [...Object.keys(KINDS), CSS_KIND];

const IMPORT_KIND = {
  Drawer: "drawer",
  Popconfirm: "confirm",
  Table: "table",
  Spin: "spin",
  Modal: "modal",
};

/**
 * Violations in one TS/TSX source: `{ kind, line, column }` (1-based line, 0-based column, like ESLint).
 * Imports of Drawer / Popconfirm / Table / Spin / Modal from "antd", `<table>` elements, and `modal.confirm(…)` /
 * `Modal.confirm(…)` calls.
 */
export function detectTs(source, fileName = "file.tsx") {
  const file = ts.createSourceFile(
    fileName,
    source,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  const found = [];
  const at = (node, kind) => {
    const { line, character } = file.getLineAndCharacterOfPosition(node.getStart(file));
    found.push({ kind, line: line + 1, column: character });
  };
  const visit = (node) => {
    if (
      ts.isImportDeclaration(node) &&
      ts.isStringLiteral(node.moduleSpecifier) &&
      node.moduleSpecifier.text === "antd" &&
      node.importClause?.namedBindings !== undefined &&
      ts.isNamedImports(node.importClause.namedBindings)
    ) {
      for (const element of node.importClause.namedBindings.elements) {
        const name = (element.propertyName ?? element.name).text;
        const kind = IMPORT_KIND[name];
        if (kind !== undefined) at(element, kind);
      }
    }
    if (
      (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) &&
      ts.isIdentifier(node.tagName) &&
      node.tagName.text === "table"
    ) {
      at(node, "table");
    }
    if (
      ts.isCallExpression(node) &&
      ts.isPropertyAccessExpression(node.expression) &&
      node.expression.name.text === "confirm" &&
      ts.isIdentifier(node.expression.expression) &&
      /^(modal|Modal)$/.test(node.expression.expression.text)
    ) {
      at(node, "confirm");
    }
    ts.forEachChild(node, visit);
  };
  visit(file);
  return found;
}

const TABLE_SELECTOR =
  /(^|[\s>+~(])(table|thead|tbody|tfoot|tr|th|td|caption)(?![\w-])|\.ant-table/;

/** Table styling in one stylesheet: `{ kind: "css-table", line, column, selector }` per offending selector. */
export function detectCss(source) {
  const found = [];
  const blank = source.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "));
  const rule = /([^{}]+)\{/g;
  let match;
  while ((match = rule.exec(blank)) !== null) {
    const prelude = match[1];
    const start = match.index + (prelude.length - prelude.trimStart().length);
    const text = prelude.trim();
    if (text.startsWith("@")) continue;
    // attribute values and strings are not selectors of table elements
    const clean = text.replace(/\[[^\]]*\]/g, "[]").replace(/(["']).*?\1/g, "");
    if (clean.split(",").some((part) => TABLE_SELECTOR.test(part.trim()))) {
      const line = blank.slice(0, start).split("\n").length;
      found.push({ kind: CSS_KIND, line, column: 0, selector: text.replace(/\s+/g, " ") });
    }
  }
  return found;
}

/** Repo-relative POSIX path from the web root, e.g. `src/modules/admin/org/OrgPage.tsx`. */
export function webPath(absolute) {
  return relative(WEB_ROOT, absolute).split(sep).join("/");
}

function walk(dir, out) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

/** Is it a guarded source (module code, not a test)? Path is web-relative POSIX. */
export function isGuardedTs(path) {
  return (
    GUARDED_DIRS.some((dir) => path.startsWith(`${dir}/`)) &&
    /\.tsx?$/.test(path) &&
    !/\.test\.tsx?$/.test(path)
  );
}
export function isGuardedCss(path) {
  return GUARDED_DIRS.some((dir) => path.startsWith(`${dir}/`)) && path.endsWith(".css");
}

/** Every violation in the tree: `Map<kind, Map<path, count>>`. */
export function scanTree() {
  const result = new Map(ALL_KINDS.map((kind) => [kind, new Map()]));
  for (const dir of GUARDED_DIRS) {
    for (const full of walk(join(WEB_ROOT, dir), [])) {
      const path = webPath(full);
      let hits = [];
      if (isGuardedTs(path)) hits = detectTs(readFileSync(full, "utf8"), full);
      else if (isGuardedCss(path)) hits = detectCss(readFileSync(full, "utf8"));
      for (const hit of hits) {
        const byPath = result.get(hit.kind);
        byPath.set(path, (byPath.get(path) ?? 0) + 1);
      }
    }
  }
  return result;
}

export function loadAllowlist() {
  return JSON.parse(readFileSync(join(WEB_ROOT, "ui-guards/allowlist.json"), "utf8"));
}
export function loadBaseline() {
  return JSON.parse(readFileSync(join(WEB_ROOT, "ui-guards/baseline.json"), "utf8"));
}
