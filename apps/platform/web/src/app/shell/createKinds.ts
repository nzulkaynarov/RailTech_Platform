import type { Me } from "../../shared/api/generated/model";
import { canEdit } from "../access";

/**
 * Виды окна «Создать» (план 2026-11-12 п. 0.1, docs/product/NAVIGATION.md): один реестр для окна и поиска ⌘K. Пункт
 * открывает форму, а не список.
 */
export type CreateGroup = "sales" | "documents";

export type CreateKindKey = "lead" | "request" | "calc" | "incoming" | "letter" | "internal";

export interface CreateKind {
  key: CreateKindKey;
  group: CreateGroup;
  /** Нужен полный доступ хотя бы к одному разделу */
  resources: readonly string[];
  /** Форма, которую открывает вид: вида без действия в окне нет */
  to: string;
  /** Слова для поиска ⌘K (строчные, три языка), кроме названия вида */
  keywords: readonly string[];
}

export const CREATE_GROUPS: readonly CreateGroup[] = ["sales", "documents"];

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
    // План 1.1: выбор заявки из «Моих расчётов» — расчёт открывается сразу с разбором файла заявки
    to: "/erp/requests?mine=1&new=calc",
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
      "записка",
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
];

let freshCounter = 0;

/** One-off mark for the navigation state: opening a kind from «Create» resets an already open form of that kind. */
export function freshMark(): number {
  freshCounter += 1;
  return freshCounter;
}

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

/** Два вида, открытые хотя бы дважды, по убыванию — из доступных сотруднику. */
export function frequentKinds(kinds: readonly CreateKind[]): CreateKind[] {
  const counts = readFrequent();
  return kinds
    .filter((kind) => (counts[kind.key] ?? 0) >= 2)
    .sort((a, b) => (counts[b.key] ?? 0) - (counts[a.key] ?? 0))
    .slice(0, 2);
}
