import type { Rule } from "eslint";

declare const plugin: { rules: Record<"no-raw-ui", Rule.RuleModule> };
export default plugin;
