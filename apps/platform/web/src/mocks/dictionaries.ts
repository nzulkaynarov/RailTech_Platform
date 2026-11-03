import { HttpResponse, http } from "msw";

import { allows } from "../app/rbac.generated";
import type {
  Dictionary,
  DictionaryItem,
  DictionaryItemIn,
  DictionaryItemPatch,
  DictionaryOrderIn,
  LetterKindList,
} from "../shared/api/generated/model";
import { readLetters } from "./fixtures/letters";
import { buildMe, readSession } from "./mockSession";

/**
 * Моки справочников как данных (EDS-REG, BFF `/dictionaries…`): виды входящих документов и способы получения — как засевает
 * миграция EDS. Живут в `localStorage` (как статьи компании): вид, добавленный администратором, делопроизводитель видит в форме
 * после смены учётной записи. Правила — как у EDS: код из названия, использованное значение не удаляется (только скрыть),
 * читать — `eds.inbox`, `eds.inbox.register` или `admin`, менять — `admin: full`.
 */
const KEY = "rt-pf-mock-dictionaries";

type Kind = "letter-kinds" | "receipt-methods" | "resolution-kinds" | "mail-types";
const CLOSED: ReadonlySet<Kind> = new Set<Kind>(["resolution-kinds"]);
type State = Record<Kind, DictionaryItem[]>;

const names = (ru: string, uz: string, en: string) => ({ ru, uz, en });

/** Действия по умолчанию, цвета и значки типов писем — закрытые списки кода (как у CRM). */
const ACTIONS: readonly [string, string, string, string][] = [
  [
    "register_incoming",
    "Зарегистрировать как входящее (ВХ) → директору",
    "Kiruvchi sifatida ro‘yxatdan o‘tkazish → direktorga",
    "Register as incoming → director",
  ],
  ["create_lead", "Создать лид → менеджеру", "Lid yaratish → menejerga", "Create a lead → manager"],
  [
    "supplier_price",
    "Загрузить прайс или КП поставщика",
    "Yetkazib beruvchi narxnomasini yuklash",
    "Upload supplier price list or quote",
  ],
  ["to_accountant", "Передать бухгалтеру", "Buxgalterga topshirish", "Hand over to the accountant"],
  [
    "archive_mailing",
    "В архив как рассылку",
    "Reklama sifatida arxivga",
    "Archive as a newsletter",
  ],
  ["reply_template", "Ответить шаблоном", "Shablon bilan javob berish", "Reply with a template"],
  ["suspicious", "В «Подозрительные» (спам)", "«Shubhali»ga (spam)", "To Suspicious (spam)"],
];
const COLORS: readonly [string, string, string, string][] = [
  ["blue", "Синий", "Ko‘k", "Blue"],
  ["green", "Зелёный", "Yashil", "Green"],
  ["gold", "Жёлтый", "Sariq", "Yellow"],
  ["red", "Красный", "Qizil", "Red"],
  ["purple", "Фиолетовый", "Binafsha", "Purple"],
  ["cyan", "Бирюзовый", "Firuza", "Cyan"],
  ["default", "Серый", "Kulrang", "Grey"],
];
const ICONS: readonly [string, string, string, string][] = [
  ["mail", "Письмо", "Xat", "Letter"],
  ["team", "Люди", "Odamlar", "People"],
  ["calendar", "Календарь", "Taqvim", "Calendar"],
  ["file", "Документ", "Hujjat", "Document"],
  ["wallet", "Деньги", "Pul", "Money"],
  ["bank", "Учреждение", "Muassasa", "Institution"],
  ["notification", "Рассылка", "Xabarnoma", "Newsletter"],
  ["stop", "Стоп", "To‘xtash", "Stop"],
];
const options = (list: readonly [string, string, string, string][]) =>
  list.map(([value, ru, uz, en]) => ({ value, name: names(ru, uz, en) }));
const mailType = (
  code: string,
  name: DictionaryItem["name"],
  position: number,
  color: string,
  icon: string,
  action: string,
  letterKind: string | null = null,
): DictionaryItem => ({
  code,
  name,
  attrs: { default_action: action, color, icon, letter_kind: letterKind },
  active: true,
  position,
});
const kindItem = (
  code: string,
  name: DictionaryItem["name"],
  position: number,
  urgent = false,
  dueDays: number | null = null,
): DictionaryItem => ({
  code,
  name,
  attrs: { urgent, due_days: dueDays },
  active: true,
  position,
});
const methodItem = (
  code: string,
  name: DictionaryItem["name"],
  position: number,
): DictionaryItem => ({
  code,
  name,
  attrs: {},
  active: true,
  position,
});

function seed(): State {
  return {
    "letter-kinds": [
      kindItem(
        "tax_notice",
        names(
          "Требование или уведомление ГНК",
          "Soliq qo‘mitasi talabnomasi yoki xabarnomasi",
          "Tax authority demand or notice",
        ),
        10,
        true,
        3,
      ),
      kindItem("bank", names("Письмо банка", "Bank xati", "Bank letter"), 20),
      kindItem(
        "supplier",
        names("Письмо поставщика", "Yetkazib beruvchi xati", "Supplier letter"),
        30,
      ),
      kindItem(
        "government",
        names("Письмо госоргана", "Davlat organi xati", "Government letter"),
        40,
      ),
      kindItem(
        "counterparty",
        names("Письмо контрагента", "Kontragent xati", "Counterparty letter"),
        50,
      ),
      kindItem("other", names("Прочее", "Boshqa", "Other"), 60),
    ],
    "receipt-methods": [
      methodItem(
        "paper",
        names("Бумага (принесли лично)", "Qog‘oz (shaxsan olib kelingan)", "Paper (handed in)"),
        10,
      ),
      methodItem("post", names("Почта", "Pochta", "Post"), 20),
      methodItem(
        "taxpayer_cabinet",
        names(
          "Кабинет налогоплательщика my.soliq",
          "Soliq to‘lovchi kabineti my.soliq",
          "Taxpayer cabinet my.soliq",
        ),
        30,
      ),
      methodItem("courier", names("Курьер", "Kuryer", "Courier"), 40),
      methodItem("email", names("E-mail", "E-mail", "Email"), 50),
    ],
    // Типы входящих писем (MAIL-TYPES): как засевает миграция CRM.
    "mail-types": [
      mailType(
        "client_request",
        names("Запрос клиента", "Mijoz so‘rovi", "Customer request"),
        10,
        "green",
        "mail",
        "create_lead",
      ),
      mailType(
        "cooperation",
        names("Предложение о сотрудничестве", "Hamkorlik taklifi", "Partnership offer"),
        20,
        "purple",
        "team",
        "register_incoming",
      ),
      mailType(
        "meeting",
        names("Приглашение на встречу", "Uchrashuvga taklif", "Meeting invitation"),
        30,
        "cyan",
        "calendar",
        "reply_template",
      ),
      mailType(
        "supplier_price",
        names(
          "КП или прайс поставщика",
          "Yetkazib beruvchi narxnomasi",
          "Supplier quote or price list",
        ),
        40,
        "blue",
        "file",
        "supplier_price",
      ),
      mailType(
        "supplier_invoice",
        names("Счёт поставщика", "Yetkazib beruvchi hisobi", "Supplier invoice"),
        50,
        "gold",
        "wallet",
        "to_accountant",
      ),
      mailType(
        "supplier_document",
        names(
          "Документ поставщика (договор, акт сверки)",
          "Yetkazib beruvchi hujjati (shartnoma, solishtirma dalolatnoma)",
          "Supplier document (contract, reconciliation act)",
        ),
        60,
        "blue",
        "file",
        "register_incoming",
        "supplier",
      ),
      mailType(
        "official",
        names(
          "Официальное письмо (госорган, банк, налоговая)",
          "Rasmiy xat (davlat organi, bank, soliq)",
          "Official letter (authority, bank, tax)",
        ),
        70,
        "red",
        "bank",
        "register_incoming",
        "government",
      ),
      mailType(
        "mailing",
        names("Рассылка", "Reklama xabarnomasi", "Newsletter"),
        80,
        "default",
        "notification",
        "archive_mailing",
      ),
      mailType("spam", names("Спам", "Spam", "Spam"), 90, "default", "stop", "suspicious"),
    ],
    // Виды резолюции — поведение кода (закрытый список): только переименовать и переставить.
    "resolution-kinds": [
      methodItem("execute", names("К исполнению", "Ijro uchun", "For execution"), 10),
      methodItem("reply", names("Подготовить ответ", "Javob tayyorlash", "Prepare a reply"), 20),
      methodItem("info", names("Для сведения", "Ma’lumot uchun", "For information"), 30),
    ],
  };
}

const CATALOG: Dictionary[] = [
  {
    kind: "mail-types",
    owner: "crm",
    area: "mail",
    name: names("Типы входящих писем", "Kiruvchi xat turlari", "Incoming mail types"),
    closed: false,
    attrs: [
      {
        key: "default_action",
        type: "choice",
        name: names("Действие по умолчанию", "Standart harakat", "Default action"),
        options: options(ACTIONS),
      },
      {
        key: "color",
        type: "choice",
        name: names("Цвет", "Rang", "Colour"),
        options: options(COLORS),
      },
      {
        key: "icon",
        type: "choice",
        name: names("Значок", "Belgi", "Icon"),
        options: options(ICONS),
      },
      {
        key: "letter_kind",
        type: "choice",
        name: names(
          "Вид документа при регистрации",
          "Ro‘yxatga olishdagi hujjat turi",
          "Document type on registration",
        ),
        options: [],
        required: false,
      },
    ],
  },
  {
    kind: "letter-kinds",
    owner: "eds",
    area: "documents",
    name: names("Виды входящих документов", "Kiruvchi hujjat turlari", "Incoming document types"),
    closed: false,
    attrs: [
      { key: "urgent", type: "boolean", name: names("Срочный", "Shoshilinch", "Urgent") },
      {
        key: "due_days",
        type: "integer",
        name: names("Срок исполнения, дней", "Ijro muddati, kun", "Due in, days"),
        minimum: 1,
        maximum: 365,
      },
    ],
  },
  {
    kind: "receipt-methods",
    owner: "eds",
    area: "documents",
    name: names("Способы получения", "Qabul qilish usullari", "Receipt methods"),
    closed: false,
    attrs: [],
  },
  {
    kind: "resolution-kinds",
    owner: "eds",
    area: "documents",
    name: names("Виды резолюции", "Rezolyutsiya turlari", "Resolution types"),
    closed: true,
    attrs: [],
  },
];

/** Каталог, как отдаёт BFF: варианты «вида документа» у типов писем — действующие виды EDS. */
function catalogWithKinds(): Dictionary[] {
  const kinds = readDictionaries()
    ["letter-kinds"].filter((item) => item.active)
    .map((item) => ({ value: item.code, name: item.name }));
  return CATALOG.map((dictionary) => ({
    ...dictionary,
    attrs: dictionary.attrs.map((attr) =>
      attr.key === "letter_kind" ? { ...attr, options: kinds } : attr,
    ),
  }));
}

let memory: State | null = null;

export function readDictionaries(): State {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (raw) return { ...seed(), ...(JSON.parse(raw) as Partial<State>) };
  } catch {
    // Хранилище недоступно — состояние в памяти.
  }
  return memory ?? seed();
}

export function writeDictionaries(state: State): void {
  memory = state;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    // Остаётся копия в памяти.
  }
}

export function resetDictionariesMock(): void {
  memory = null;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // Нечего сбрасывать.
  }
}

const kindsOf = (kind: Kind): DictionaryItem[] => readDictionaries()[kind];

/** Действующие виды документа в форме прежнего ресурса `/eds/letter-kinds`. */
export function activeLetterKinds(): LetterKindList {
  return {
    items: kindsOf("letter-kinds")
      .filter((item) => item.active)
      .map((item) => ({
        code: item.code,
        name: item.name,
        urgent: item.attrs["urgent"] === true,
        due_days: typeof item.attrs["due_days"] === "number" ? item.attrs["due_days"] : null,
      })),
  };
}

export function isActiveValue(kind: Kind, code: string): boolean {
  return readDictionaries()[kind].some((item) => item.code === code && item.active);
}

/** Типы, уже стоящие у писем (подставляет мок почты): использованный тип не удаляется, только скрывается. */
let mailTypeUsage: () => Set<string> = () => new Set();
export function setMailTypeUsage(fn: () => Set<string>): void {
  mailTypeUsage = fn;
}

function usedCodes(kind: Kind): Set<string> {
  if (kind === "mail-types") return mailTypeUsage();
  return new Set(
    readLetters().flatMap((letter) => {
      const code =
        kind === "letter-kinds"
          ? letter.kind
          : kind === "receipt-methods"
            ? letter.receipt_method
            : letter.office_resolution?.kind;
      return code ? [code] : [];
    }),
  );
}

function failure(status: number, code: string, message: string, details?: Record<string, unknown>) {
  return HttpResponse.json(
    { code, message, source: status === 403 ? "bff" : "eds", ...(details ? { details } : {}) },
    { status },
  );
}

function canRead(): boolean {
  const session = readSession();
  const me = session ? buildMe({ ...session, activeRole: null }) : null;
  if (!me) return false;
  const r = me.resources;
  return (
    allows(r, "eds.inbox", "read") ||
    allows(r, "eds.inbox.register", "full") ||
    allows(r, "crm.leads.triage", "read") ||
    allows(r, "admin", "read")
  );
}

function isAdmin(): boolean {
  const session = readSession();
  const me = session ? buildMe({ ...session, activeRole: null }) : null;
  return Boolean(me && allows(me.resources, "admin", "full"));
}

const isKind = (value: unknown): value is Kind =>
  value === "letter-kinds" ||
  value === "receipt-methods" ||
  value === "resolution-kinds" ||
  value === "mail-types";

const closedFailure = () =>
  failure(
    409,
    "CONFLICT",
    "Этот список задаёт поведение системы: его можно только переименовать.",
    {
      reason: "dictionary_closed",
    },
  );

const TRANSLIT: Record<string, string> = Object.fromEntries(
  "а:a б:b в:v г:g д:d е:e ё:e ж:zh з:z и:i й:y к:k л:l м:m н:n о:o п:p р:r с:s т:t у:u ф:f х:h ц:ts ч:ch ш:sh щ:sch ъ: ы:y ь: э:e ю:yu я:ya"
    .split(" ")
    .map((pair) => pair.split(":") as [string, string]),
);

function slug(name: string): string {
  const latin = name.toLowerCase().replace(/[а-яё]/g, (ch) => TRANSLIT[ch] ?? ch);
  const text = latin
    .replace(/[^a-z]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 28)
    .replace(/_+$/, "");
  return text || "item";
}

function withUsed(kind: Kind, items: DictionaryItem[]): DictionaryItem[] {
  const used = usedCodes(kind);
  return items.map((item) => ({ ...item, used: used.has(item.code) }));
}

const sorted = (items: DictionaryItem[]) => [...items].sort((a, b) => a.position - b.position);

export const dictionariesHandlers = [
  http.get("*/dictionaries", () => {
    if (!readSession()) return failure(401, "SESSION_EXPIRED", "Сессия истекла");
    if (!isAdmin() && !canRead())
      return failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.");
    return HttpResponse.json({ items: catalogWithKinds(), unavailable: [] });
  }),

  http.get("*/dictionaries/:kind", ({ params, request }) => {
    if (!readSession()) return failure(401, "SESSION_EXPIRED", "Сессия истекла");
    if (!isKind(params["kind"])) return failure(404, "NOT_FOUND", "Такого справочника нет.");
    if (!canRead()) return failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.");
    const kind = params["kind"];
    const all = new URL(request.url).searchParams.get("include_hidden") === "true";
    const items = sorted(readDictionaries()[kind]);
    return HttpResponse.json({
      items: all ? withUsed(kind, items) : items.filter((item) => item.active),
    });
  }),

  http.post("*/dictionaries/:kind", async ({ params, request }) => {
    if (!isKind(params["kind"])) return failure(404, "NOT_FOUND", "Такого справочника нет.");
    if (!isAdmin()) return failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.");
    const kind = params["kind"];
    if (CLOSED.has(kind)) return closedFailure();
    const body = (await request.json()) as DictionaryItemIn;
    const state = readDictionaries();
    const ru = body.name.ru.trim();
    if (state[kind].some((item) => item.name.ru.toLowerCase() === ru.toLowerCase())) {
      return failure(409, "CONFLICT", "Такое название уже есть в справочнике.", {
        reason: "name_taken",
      });
    }
    const base = slug(body.name.en?.trim() || ru);
    const taken = new Set(state[kind].map((item) => item.code));
    let code = base;
    for (let i = 0; taken.has(code); i += 1) code = `${base}_${String.fromCharCode(97 + i)}`;
    if (kind === "mail-types" && typeof body.attrs?.["default_action"] !== "string") {
      return failure(422, "VALIDATION_FAILED", "Выберите действие по умолчанию.", {
        fields: ["attrs.default_action"],
      });
    }
    const defaults: DictionaryItem["attrs"] =
      kind === "letter-kinds"
        ? { urgent: false, due_days: null }
        : kind === "mail-types"
          ? { color: "default", icon: "mail", letter_kind: null }
          : {};
    const created: DictionaryItem = {
      code,
      name: { ru, uz: body.name.uz?.trim() ?? "", en: body.name.en?.trim() ?? "" },
      attrs: { ...defaults, ...(body.attrs ?? {}) },
      active: true,
      position: Math.max(0, ...state[kind].map((item) => item.position)) + 10,
      used: false,
    };
    writeDictionaries({ ...state, [kind]: [...state[kind], created] });
    return HttpResponse.json(created, { status: 201 });
  }),

  http.put("*/dictionaries/:kind/order", async ({ params, request }) => {
    if (!isKind(params["kind"])) return failure(404, "NOT_FOUND", "Такого справочника нет.");
    if (!isAdmin()) return failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.");
    const kind = params["kind"];
    const { codes } = (await request.json()) as DictionaryOrderIn;
    const state = readDictionaries();
    const byCode = new Map(state[kind].map((item) => [item.code, item]));
    if (codes.length !== byCode.size || codes.some((code) => !byCode.has(code))) {
      return failure(422, "VALIDATION_FAILED", "Нужен полный список значений справочника.", {
        fields: ["codes"],
      });
    }
    const items = codes.flatMap((code, index) => {
      const item = byCode.get(code);
      return item ? [{ ...item, position: (index + 1) * 10 }] : [];
    });
    writeDictionaries({ ...state, [kind]: items });
    return HttpResponse.json({ items: withUsed(kind, items) });
  }),

  http.patch("*/dictionaries/:kind/:code", async ({ params, request }) => {
    if (!isKind(params["kind"])) return failure(404, "NOT_FOUND", "Такого справочника нет.");
    if (!isAdmin()) return failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.");
    const kind = params["kind"];
    const patch = (await request.json()) as DictionaryItemPatch;
    if (CLOSED.has(kind) && patch.active !== undefined) return closedFailure();
    const state = readDictionaries();
    const current = state[kind].find((item) => item.code === params["code"]);
    if (!current) return failure(404, "NOT_FOUND", "Такого значения в справочнике нет.");
    const ru = patch.name?.ru.trim();
    if (
      ru &&
      state[kind].some(
        (item) => item.code !== current.code && item.name.ru.toLowerCase() === ru.toLowerCase(),
      )
    ) {
      return failure(409, "CONFLICT", "Такое название уже есть в справочнике.", {
        reason: "name_taken",
      });
    }
    const next: DictionaryItem = {
      ...current,
      ...(patch.name
        ? { name: { ru: ru ?? current.name.ru, uz: patch.name.uz ?? "", en: patch.name.en ?? "" } }
        : {}),
      ...(patch.attrs ? { attrs: { ...current.attrs, ...patch.attrs } } : {}),
      ...(patch.active === undefined ? {} : { active: patch.active }),
    };
    writeDictionaries({
      ...state,
      [kind]: state[kind].map((item) => (item.code === current.code ? next : item)),
    });
    return HttpResponse.json({ ...next, used: usedCodes(kind).has(next.code) });
  }),

  http.delete("*/dictionaries/:kind/:code", ({ params }) => {
    if (!isKind(params["kind"])) return failure(404, "NOT_FOUND", "Такого справочника нет.");
    if (!isAdmin()) return failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.");
    const kind = params["kind"];
    if (CLOSED.has(kind)) return closedFailure();
    const code = String(params["code"]);
    if (usedCodes(kind).has(code)) {
      return failure(409, "CONFLICT", "Значение уже есть у писем — его можно только скрыть.", {
        reason: "value_in_use",
      });
    }
    const state = readDictionaries();
    writeDictionaries({ ...state, [kind]: state[kind].filter((item) => item.code !== code) });
    return new HttpResponse(null, { status: 204 });
  }),
];
