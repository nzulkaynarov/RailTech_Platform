import { levelOf } from "../../app/access";
import type { Me, QueueItem } from "../../shared/api/generated/model";
import type { StatusTone } from "../../shared/lib/statuses";

export type Translate = (key: string, options?: Record<string, unknown>) => string;

/** Бейдж срока (SPEC-v3 §7.1): красный «срок сегодня», золотой «завтра», фиолетовый «служебка», серый — дата или «без срока». */
export function dueBadge(
  item: Pick<QueueItem, "due_label" | "due_at">,
  t: Translate,
  formatShort: (value: string) => string,
): { tone: StatusTone; label: string } {
  switch (item.due_label) {
    case "overdue":
      return { tone: "red", label: t("modules:dashboard.queue.due.overdue") };
    case "today":
      return { tone: "red", label: t("modules:dashboard.queue.due.today") };
    case "tomorrow":
      return { tone: "gold", label: t("modules:dashboard.queue.due.tomorrow") };
    case "memo":
      return { tone: "purple", label: t("modules:dashboard.queue.due.memo") };
    case "later":
      return {
        tone: "default",
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
  "director" | "accountant" | "supply" | "engineer" | "manager" | "admin" | "default";

/**
 * Вид пустого состояния «Моих задач» по разделам каталога, которые дают роли «вида» (`Me.resources`), а не по кодам ролей
 * (CONVENTIONS §2 п. 6): решения директора (письма, КП, служебки), платёжки бухгалтера, визы расчёта (товары — снабженец,
 * услуги — гл. инженер), лиды менеджера, настройки администратора. Порядок — от решений к исполнению; роль без вида
 * получает нейтральный текст.
 */
export function queueEmptyKind(me: Me): QueueEmptyKind {
  const full = (resource: string) => levelOf(me, resource) === "full";
  if (full("eds.inbox") || full("eds.drafts") || full("eds.memo.approve")) return "director";
  if (full("eds.payments")) return "accountant";
  if (full("erp.calc.goods")) return "supply";
  if (full("erp.calc.services")) return "engineer";
  if (full("crm.leads")) return "manager";
  if (full("admin")) return "admin";
  return "default";
}

/** Строка очереди срочная — «срок сегодня» или «просрочено»: у её «Открыть» primary (P2-9). */
export function isUrgent(item: Pick<QueueItem, "due_label">): boolean {
  return item.due_label === "overdue" || item.due_label === "today";
}
