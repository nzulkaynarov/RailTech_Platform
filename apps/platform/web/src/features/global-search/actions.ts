import { canEdit } from "../../app/access";
import type { Me } from "../../shared/api/generated/model";

/**
 * Действия, которые находит поиск по словам («создать заявку», «служебка», «пригласить»; W15-H2, UX-оценка P1-8): строка
 * в результатах ведёт на экран действия, а если у него ещё нет экрана — в поповер «Где посмотреть» (мост H1). Показываются
 * только действия, доступные ролям сотрудника: право на запись в разделе каталога (`resource`).
 */
export type SearchActionKey = "createRequest" | "createDocument" | "inviteEmployee";

export interface SearchAction {
  key: SearchActionKey;
  /** Слова на трёх языках (строчные): запрос подходит, если содержит слово или входит в него */
  keywords: readonly string[];
  /** Куда ведёт действие; раздел без экрана — «Где посмотреть» */
  to: string;
  /** Раздел каталога, на запись в который нужно право */
  resource: string;
}

export const SEARCH_ACTIONS: readonly SearchAction[] = [
  {
    key: "createRequest",
    keywords: [
      "создать заявку",
      "новая заявка",
      "заявку",
      "create request",
      "new request",
      "ariza yaratish",
    ],
    to: "/crm/leads",
    resource: "crm.clients",
  },
  {
    key: "createDocument",
    keywords: [
      "служебка",
      "служебную записку",
      "создать документ",
      "записку",
      "memo",
      "create document",
      "xizmat xati",
      "hujjat yaratish",
    ],
    to: "/eds/new?type=memo",
    resource: "eds.memo.create",
  },
  {
    key: "inviteEmployee",
    keywords: [
      "пригласить",
      "пригласить сотрудника",
      "invite",
      "invite employee",
      "taklif qilish",
      "xodim",
    ],
    to: "/admin/org?invite=open&panel=open",
    resource: "admin",
  },
];

/** Короче четырёх символов запрос слишком общий: «заяв» уже действие, «за» подошло бы ко всему. */
const MIN_ACTION_QUERY = 4;

/** Запрос — начало слова или фразы действия («заявк» → «заявку»), либо в запросе есть вся фраза («создать заявку на ремонт»). */
function matches(query: string, keyword: string): boolean {
  return (
    keyword.startsWith(query) ||
    keyword.split(" ").some((word) => word.startsWith(query)) ||
    query.includes(keyword)
  );
}

export function matchActions(me: Me, query: string): SearchAction[] {
  const q = query.trim().toLocaleLowerCase();
  if (q.length < MIN_ACTION_QUERY) return [];
  return SEARCH_ACTIONS.filter(
    (action) => canEdit(me, action.resource) && action.keywords.some((word) => matches(q, word)),
  );
}
