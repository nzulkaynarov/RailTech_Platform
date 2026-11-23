import { levelOf } from "../../app/access";
import { SECTION_ONLY_KINDS, type SectionOnlyKind, hasKind } from "../../features/help/startKinds";
import type { Me, QueueItem } from "../../shared/api/generated/model";
import { statusTone } from "../../shared/lib/statuses";

export type Translate = (key: string, options?: Record<string, unknown>) => string;

/** Бейдж срока (SPEC-v3 §7.1): красный «срок сегодня», золотой «завтра», фиолетовый «служебка», серый — дата или «без срока». */
export function dueBadge(
  item: Pick<QueueItem, "due_label" | "due_at">,
  t: Translate,
  formatShort: (value: string) => string,
): { tone: ReturnType<typeof statusTone>; label: string } {
  switch (item.due_label) {
    case "overdue":
      return {
        tone: statusTone("due", "overdue"),
        label: t("modules:dashboard.queue.due.overdue"),
      };
    case "today":
      return { tone: statusTone("due", "today"), label: t("modules:dashboard.queue.due.today") };
    case "tomorrow":
      return {
        tone: statusTone("due", "tomorrow"),
        label: t("modules:dashboard.queue.due.tomorrow"),
      };
    case "memo":
      return { tone: statusTone("due", "memo"), label: t("modules:dashboard.queue.due.memo") };
    case "later":
      return {
        tone: statusTone("due", "later"),
        label: item.due_at
          ? t("modules:dashboard.queue.due.until", { date: formatShort(item.due_at) })
          : t("modules:dashboard.queue.due.none"),
      };
  }
}

/** Форма числа для «N решений»: правила множественного числа языка, ключи `one|few|many|other` есть во всех языках. */
export function pluralForm(language: string, count: number): "one" | "few" | "many" | "other" {
  const rule = new Intl.PluralRules(language).select(count);
  return rule === "one" || rule === "few" || rule === "many" ? rule : "other";
}

/** Чей пустой экран показывать: набор текстов `modules:dashboard.queue.empty.<вид>` (UX-оценка P0-3). */
export type QueueEmptyKind =
  | "director"
  | "universal"
  | "accountant"
  | "supply"
  | "engineer"
  | "manager"
  | "admin"
  | SectionOnlyKind
  | "default";

/** Основной вид пустого состояния — по приоритету «от решений к исполнению»; `default` — ни одного. */
function primaryEmptyKind(me: Me): QueueEmptyKind {
  const full = (resource: string) => levelOf(me, resource) === "full";
  if (full("eds.inbox") || full("eds.drafts") || full("eds.memo.approve")) return "director";
  // Совмещённая роль (продажи, расчёт, счета и оплаты, D2-8): пустой экран перечисляет всю её работу, а не только платёжки
  if (full("eds.payments") && full("crm.leads") && full("erp.calc")) return "universal";
  if (full("eds.payments")) return "accountant";
  if (full("erp.calc.goods")) return "supply";
  if (full("erp.calc.services")) return "engineer";
  if (full("crm.leads")) return "manager";
  if (full("admin")) return "admin";
  return "default";
}

/** Виды рабочих разделов, добавляемые к основному (порядок — как в `START_KINDS`); у каждого свой текст пустой «Главной». */
const ADDITIVE_KINDS = ["admin", "manager", "supply", "engineer", "accountant"] as const;

/** Что уже перечисляет текст основного вида — его не повторяем (совмещённая роль перечисляет сразу лиды, расчёт и оплаты). */
const COVERED_BY_PRIMARY: Partial<Record<QueueEmptyKind, readonly QueueEmptyKind[]>> = {
  universal: ["accountant", "manager", "supply", "engineer"],
};

/**
 * Виды пустого состояния «Моих задач» по разделам каталога, которые дают роли «вида» (`Me.resources`), а не по кодам ролей
 * (CONVENTIONS §2 п. 6): решения директора (письма, КП, служебки), платёжки бухгалтера, визы расчёта (товары — снабженец,
 * услуги — гл. инженер), лиды менеджера, настройки администратора. Основной вид — по порядку от решений к исполнению; к нему
 * добавляются остальные виды по разделам, которые он не покрывает (`COVERED_BY_PRIMARY`, `unless` в `KIND_SECTIONS`), и виды
 * делопроизводителя, юриста и подписанта — у человека с несколькими ролями тексты по каждому его разделу. Ничего не
 * подошло — один нейтральный `default`.
 */
export function queueEmptyKinds(me: Me): QueueEmptyKind[] {
  const primary = primaryEmptyKind(me);
  const covered = COVERED_BY_PRIMARY[primary] ?? [];
  const more: QueueEmptyKind[] = [
    ...ADDITIVE_KINDS.filter(
      (kind) => kind !== primary && !covered.includes(kind) && hasKind(me, kind),
    ),
    ...SECTION_ONLY_KINDS.filter((kind) => hasKind(me, kind)),
  ];
  const kinds: QueueEmptyKind[] = primary === "default" ? more : [primary, ...more];
  return kinds.length > 0 ? kinds : ["default"];
}

/** Строка очереди срочная — «срок сегодня» или «просрочено»: у её «Открыть» primary (P2-9). */
export function isUrgent(item: Pick<QueueItem, "due_label">): boolean {
  return item.due_label === "overdue" || item.due_label === "today";
}
