import type { Me } from "../../shared/api/generated/model";
import { canEdit } from "../access";

/**
 * Виды окна «Создать» (план 2026-11-12 п. 0.1, docs/product/NAVIGATION.md): один реестр для окна и поиска ⌘K. Пункт
 * открывает форму, а не список; без адреса вид виден приглушённым и подписан, когда появится.
 */
export type CreateGroup = "sales" | "documents" | "talk";

export type CreateKindKey =
  "lead" | "request" | "calc" | "incoming" | "letter" | "internal" | "message" | "assignment";

export interface CreateKind {
  key: CreateKindKey;
  group: CreateGroup;
  /** Нужен полный доступ хотя бы к одному разделу */
  resources: readonly string[];
  /** Форма; нет — вид ещё не готов */
  to?: string;
  /** Когда появится, если адреса нет: ключ `shell:create.<soon>` */
  soon?: "soon" | "withChats";
  /** Слова для поиска ⌘K (строчные, три языка), кроме названия вида */
  keywords: readonly string[];
}

export const CREATE_GROUPS: readonly CreateGroup[] = ["sales", "documents", "talk"];

export const CREATE_KINDS: readonly CreateKind[] = [
  {
    key: "lead",
    group: "sales",
    resources: ["crm.leads"],
    to: "/crm/leads?new=1&panel=open&tab=card",
    keywords: ["новый лид", "звонок", "обращение", "new lead", "call", "yangi lid"],
  },
  {
    key: "request",
    group: "sales",
    resources: ["crm.clients"],
    to: "/crm/clients?create=1&panel=open&tab=card",
    keywords: ["заявку", "новая заявка", "создать заявку", "new request", "ariza yaratish"],
  },
  {
    key: "calc",
    group: "sales",
    resources: ["erp.calc"],
    soon: "soon",
    keywords: ["расчёт", "расчет", "costing", "hisob-kitob"],
  },
  {
    key: "incoming",
    group: "documents",
    resources: ["eds.inbox.register"],
    to: "/eds/register",
    keywords: ["зарегистрировать", "входящее", "register", "incoming", "kiruvchi"],
  },
  {
    key: "letter",
    group: "documents",
    resources: ["eds.memo.create"],
    to: "/eds/new?type=letter",
    keywords: ["письмо", "исходящее", "letter", "outgoing", "xat"],
  },
  {
    key: "internal",
    group: "documents",
    resources: ["eds.memo.create"],
    to: "/eds/new?type=memo",
    keywords: [
      "служебка",
      "служебную записку",
      "записку",
      "заявление",
      "отчёт",
      "отчет",
      "memo",
      "application",
      "report",
      "xizmat xati",
      "hisobot",
    ],
  },
  {
    key: "message",
    group: "talk",
    resources: ["chats.internal"],
    soon: "withChats",
    keywords: ["сообщение", "написать", "message", "xabar"],
  },
  {
    key: "assignment",
    group: "talk",
    resources: ["eds.inbox"],
    soon: "withChats",
    keywords: ["поручение", "задачу", "assignment", "topshiriq"],
  },
];

/** Виды, которые сотруднику положены по ролям; чего нельзя — того нет вовсе. */
export function createKindsFor(me: Me | null | undefined): CreateKind[] {
  if (!me) return [];
  return CREATE_KINDS.filter((kind) => kind.resources.some((resource) => canEdit(me, resource)));
}

const FREQUENT_KEY = "pf.create.frequent";

/** Сколько раз сотрудник открывал вид — для «Часто у вас»; браузер может не дать хранилище — тогда пусто. */
export function readFrequent(): Partial<Record<CreateKindKey, number>> {
  try {
    const raw = window.localStorage.getItem(FREQUENT_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

export function countFrequent(key: CreateKindKey): void {
  try {
    const next = readFrequent();
    next[key] = (next[key] ?? 0) + 1;
    window.localStorage.setItem(FREQUENT_KEY, JSON.stringify(next));
  } catch {
    // хранилище недоступно — «Часто у вас» просто не появится
  }
}

/** Два вида, открытые хотя бы дважды, по убыванию — из доступных сотруднику и готовых. */
export function frequentKinds(kinds: readonly CreateKind[]): CreateKind[] {
  const counts = readFrequent();
  return kinds
    .filter((kind) => kind.to !== undefined && (counts[kind.key] ?? 0) >= 2)
    .sort((a, b) => (counts[b.key] ?? 0) - (counts[a.key] ?? 0))
    .slice(0, 2);
}
