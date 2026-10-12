/** Песочница «Проверить бота»: лента и подписи решения (без React). */
import type { SandboxTurnOut, SandboxWhy } from "../api/generated/model";
import { t } from "../i18n/ru";

export type SandboxEntry =
  { id: number; role: "lead"; text: string } | { id: number; role: "bot"; turn: SandboxTurnOut };

/** Подпись решения бота; неизвестное значение — как есть (новые действия агента). */
export function decisionLabel(decision: string): string {
  return t.sandbox.decisions[decision] ?? decision;
}

/** Строки блока «Почему так»: только непустые факты, в порядке важности. */
export function whyLines(why: SandboxWhy): string[] {
  const lines = [`${t.sandbox.why.decision}: ${decisionLabel(why.decision)}`];
  if (why.reason) lines.push(`${t.sandbox.why.reason}: ${why.reason}`);
  if (why.best_score !== null) lines.push(`${t.sandbox.why.score}: ${why.best_score.toFixed(2)}`);
  lines.push(
    `${t.sandbox.why.documents}: ${why.documents.length ? why.documents.join(", ") : t.sandbox.why.none}`,
  );
  if (why.triggers.length) lines.push(`${t.sandbox.why.triggers}: ${why.triggers.join(", ")}`);
  return lines;
}
