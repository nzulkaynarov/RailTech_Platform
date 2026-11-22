// ESLint rule `rt-ui/no-raw-ui` (ЕВ-1а): raw AntD Drawer / Modal / Popconfirm / Table / Spin, `<table>` and
// `modal.confirm()` are forbidden in module code. Today's violations live in `allowlist.json` (path + reason); the list
// may only shrink — `src/test/uiGuards.test.ts` fails when an entry is stale or the baseline count is exceeded.
import { KINDS, detectTs, isGuardedTs, loadAllowlist, webPath } from "./detect.mjs";

const allow = loadAllowlist();
const allowed = new Map(
  Object.entries(allow).map(([kind, entries]) => [
    kind,
    new Set(entries.map((entry) => entry.path)),
  ]),
);

const rule = {
  meta: {
    type: "problem",
    schema: [],
    messages: Object.fromEntries(Object.keys(KINDS).map((kind) => [kind, "{{text}}"])),
  },
  create(context) {
    const path = webPath(context.filename);
    if (!isGuardedTs(path)) return {};
    return {
      Program() {
        for (const hit of detectTs(context.sourceCode.text, context.filename)) {
          if (allowed.get(hit.kind)?.has(path)) continue;
          context.report({
            loc: { line: hit.line, column: hit.column },
            messageId: hit.kind,
            data: {
              text: `${KINDS[hit.kind]} (allow-list: apps/platform/web/ui-guards/allowlist.json only for existing code)`,
            },
          });
        }
      },
    };
  },
};

export default { rules: { "no-raw-ui": rule } };
