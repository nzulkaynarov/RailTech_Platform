// СЦ-2: прогон сквозных сценариев на стенде `rt-scen` (план §4.0a, разбор docs/research/2026-11-19-scenarios-no-dead-ends.md §5).
// Надстройка над помощниками гейта D2 (d26-gate/common.mjs): та же авторизация, отчёт и снимки.
// Запуск из корня worktree:
//   QA_BASE=http://platform.localhost:8111 QA_OUT=<вне репозитория> QA_SHOTS=<вне репозитория> \
//   QA_COMPOSE="docker compose -p rt-scen -f infra/compose/base.yml -f infra/compose/dev.yml --env-file .env" \
//   node docs/audits/qa/sc2-walk/run.mjs <сценарии>
export * from "../d26-gate/common.mjs";
import { PEOPLE, np, pwOf, signIn, state } from "../d26-gate/common.mjs";

/** Вход ролью гейта D2 (`admin` — администратор первого запуска). */
export async function as(browser, r, role, width = 1440) {
  const { page } = await np(browser, width);
  const email = role === "admin" ? state().adminEmail : PEOPLE[role].email;
  const pw = role === "admin" ? (state().passwords?.[email] ?? state().adminPw) : pwOf(email);
  await signIn(page, r, email, pw);
  return page;
}

/** Видимый текст области без пустых строк (для записи «что видит человек»). */
export async function seen(page, selector = "main", max = 900) {
  const loc = page.locator(selector).first();
  const text = (await loc.innerText().catch(() => "")).replace(/\n{2,}/g, "\n").trim();
  return text.slice(0, max);
}

/** Строка наблюдения сценария: шаг · что видит · что дальше · тупик (пусто — нет). */
export function obs(r, stepName, { sees = "", next = "", dead = "" } = {}) {
  r.rows.push({ kind: "obs", step: stepName, sees, next, dead });
  console.log(`OBS  [${r.id}] ${stepName}\n     видит: ${sees.replace(/\n/g, " ⏎ ").slice(0, 400)}\n     дальше: ${next}\n     тупик: ${dead || "—"}`);
}
