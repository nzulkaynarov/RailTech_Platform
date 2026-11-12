import { canEdit } from "../../app/access";
import { CREATE_KINDS, type CreateKindKey } from "../../app/shell/createKinds";
import type { Me } from "../../shared/api/generated/model";

/**
 * Действия, которые находит поиск по словам («создать заявку», «служебка», «пригласить»; W15-H2, UX-оценка P1-8): строка
 * в результатах ведёт на экран действия. Виды «Создать» берутся из того же реестра, что и окно «Создать» (план 2026-11-12
 * п. 0.1); показываются только готовые и доступные ролям сотрудника (право на запись в разделе каталога).
 */
export interface SearchAction {
  /** Вид окна «Создать» или отдельное действие */
  key: CreateKindKey | "inviteEmployee";
  /** Действие — вид окна «Создать»: подпись «Создать · <вид>» */
  create: boolean;
  /** Слова на трёх языках (строчные): запрос подходит, если содержит слово или входит в него */
  keywords: readonly string[];
  /** Куда ведёт действие */
  to: string;
  /** Разделы каталога: нужно право записи хотя бы в одном */
  resources: readonly string[];
}

const INVITE: SearchAction = {
  key: "inviteEmployee",
  create: false,
  keywords: [
    "пригласить",
    "пригласить сотрудника",
    "invite",
    "invite employee",
    "taklif qilish",
    "xodim",
  ],
  to: "/admin/org?invite=open&panel=open",
  resources: ["admin"],
};

export const SEARCH_ACTIONS: readonly SearchAction[] = [
  ...CREATE_KINDS.flatMap((kind) =>
    kind.to === undefined
      ? []
      : [
          {
            key: kind.key,
            create: true,
            keywords: kind.keywords,
            to: kind.to,
            resources: kind.resources,
          },
        ],
  ),
  INVITE,
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
    (action) =>
      action.resources.some((resource) => canEdit(me, resource)) &&
      action.keywords.some((word) => matches(q, word)),
  );
}
