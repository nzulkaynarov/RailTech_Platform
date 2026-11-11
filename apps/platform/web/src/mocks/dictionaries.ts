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
import { ERP_CATALOG, canReadErpDictionaries } from "./erpDictionaries";
import { readLetters } from "./fixtures/letters";
import { buildMe, readSession } from "./mockSession";

/**
 * Моки справочников как данных (EDS-REG, BFF `/dictionaries…`): виды входящих документов и способы получения — как засевает
 * миграция EDS. Живут в `localStorage` (как статьи компании): вид, добавленный администратором, делопроизводитель видит в форме
 * после смены учётной записи. Правила — как у EDS: код из названия, использованное значение не удаляется (только скрыть),
 * читать — `eds.inbox`, `eds.inbox.register` или `admin`, менять — `admin: full`.
 */
const KEY = "rt-pf-mock-dictionaries";

type Kind =
  "letter-kinds" | "receipt-methods" | "resolution-kinds" | "mail-types" | "signing-kinds";
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
    "Загрузить прайс или КП партнёра",
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
        names("Письмо партнёра", "Yetkazib beruvchi xati", "Supplier letter"),
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
    // Виды документов для подписи (SIGN-2): как засевает миграция EDS.
    "signing-kinds": [
      methodItem("letter_out", names("Исходящее письмо", "Chiquvchi xat", "Outgoing letter"), 10),
      methodItem("quote", names("Коммерческое предложение", "Tijorat taklifi", "Quotation"), 20),
      methodItem("contract", names("Договор", "Shartnoma", "Contract"), 30),
      methodItem("invoice", names("Счёт", "Hisob", "Invoice"), 40),
      methodItem("act", names("Акт", "Dalolatnoma", "Act"), 50),
      methodItem("memo", names("Служебная записка", "Xizmat xati", "Memo"), 60),
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
          "КП или прайс партнёра",
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
        names("Счёт партнёра", "Yetkazib beruvchi hisobi", "Supplier invoice"),
        50,
        "gold",
        "wallet",
        "to_accountant",
      ),
      mailType(
        "supplier_document",
        names(
          "Документ партнёра (договор, акт сверки)",
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
    kind: "signing-kinds",
    owner: "eds",
    area: "documents",
    name: names(
      "Виды документов для подписи",
      "Imzolanadigan hujjat turlari",
      "Document types for signing",
    ),
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
  const letterKinds = readDictionaries()["letter-kinds"];
  const kinds = letterKinds
    .filter((item) => item.active)
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

/** Виды, уже стоящие в полномочиях подписи (подставляет мок «Прав подписи»): использованный вид только скрывается. */
let signingKindUsage: () => Set<string> = () => new Set();
export function setSigningKindUsage(fn: () => Set<string>): void {
  signingKindUsage = fn;
}

function usedCodes(kind: Kind): Set<string> {
  if (kind === "mail-types") return mailTypeUsage();
  if (kind === "signing-kinds") return signingKindUsage();
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
    allows(r, "eds.signing.manage", "full") ||
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
  value === "mail-types" ||
  value === "signing-kinds";

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
    // Как BFF: каждый видит справочники, которые ему положено читать (решение 2026-11-11)
    const own = isAdmin() || canRead() ? catalogWithKinds() : [];
    const erp = canReadErpDictionaries() ? ERP_CATALOG : [];
    if (own.length + erp.length === 0)
      return failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.");
    return HttpResponse.json({ items: [...own, ...erp], unavailable: [] });
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

  // Файл справочника (решение владельца 2026-11-11): мок понимает csv; правила — как у BFF.
  http.get("*/dictionaries/:kind/export", ({ params }) => {
    if (!isKind(params["kind"])) return failure(404, "NOT_FOUND", "Такого справочника нет.");
    const kind = params["kind"];
    const attrs = catalogWithKinds().find((d) => d.kind === kind)?.attrs ?? [];
    const header = ["code", "name_ru", "name_uz", "name_en", "active", ...attrs.map((a) => a.key)];
    const lines = sorted(readDictionaries()[kind]).map((item) =>
      [
        item.code,
        item.name.ru,
        item.name.uz,
        item.name.en,
        item.active ? "да" : "нет",
        ...attrs.map((a) => String(item.attrs[a.key] ?? "")),
      ].join(";"),
    );
    return new HttpResponse([header.join(";"), ...lines].join("\n"), {
      headers: {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": `attachment; filename="${kind}.csv"`,
      },
    });
  }),
  http.post("*/dictionaries/:kind/import", async ({ params, request }) => {
    if (!isKind(params["kind"])) return failure(404, "NOT_FOUND", "Такого справочника нет.");
    if (!isAdmin()) return failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.");
    const kind = params["kind"];
    const apply = new URL(request.url).searchParams.get("dry_run") === "false";
    const text = (await request.text()).replace(/^\uFEFF/, "");
    const table = text
      .split(/\r?\n/)
      .filter((line) => line.trim())
      .map((line) => line.split(";").map((cell) => cell.trim()));
    const header = (table[0] ?? []).map((h) => h.toLowerCase());
    if (!header.includes("code") || !header.includes("name_ru")) {
      return failure(422, "VALIDATION_FAILED", "В шапке нет столбцов: code, name_ru.", {
        fields: ["file"],
        reason: "missing_columns",
      });
    }
    const state = readDictionaries();
    const items = [...state[kind]];
    const yes = (v: string) => ["да", "1", "true", "yes", "ha"].includes(v.toLowerCase());
    const rows = table.slice(1).map((cells, index) => {
      const cell = (name: string) => cells[header.indexOf(name)] ?? "";
      const code = cell("code").toLowerCase() || null;
      const name = { ru: cell("name_ru"), uz: cell("name_uz"), en: cell("name_en") };
      const current = code ? items.find((i) => i.code === code) : undefined;
      if (code && !current) {
        return {
          line: index + 2,
          code,
          name: name.ru,
          action: "error" as const,
          fields: [],
          errors: [{ field: "code", reason: "unknown" }],
        };
      }
      if (!current && !name.ru) {
        return {
          line: index + 2,
          code,
          name: "",
          action: "error" as const,
          fields: [],
          errors: [{ field: "name_ru", reason: "required" }],
        };
      }
      if (!current) {
        return {
          line: index + 2,
          code: null,
          name: name.ru,
          action: "add" as const,
          fields: [],
          errors: [],
          name3: name,
        };
      }
      const fields: string[] = [];
      for (const lang of ["ru", "uz", "en"] as const) {
        if (name[lang] && name[lang] !== current.name[lang]) fields.push(`name_${lang}`);
      }
      if (cell("active") && yes(cell("active")) !== current.active) fields.push("active");
      return {
        line: index + 2,
        code,
        name: name.ru || current.name.ru,
        action: fields.length ? ("update" as const) : ("unchanged" as const),
        fields,
        errors: [],
        name3: name,
        active: cell("active") ? yes(cell("active")) : current.active,
      };
    });
    const failed = rows.filter((r) => r.action === "error").length;
    const applied = apply && failed === 0;
    if (applied) {
      for (const row of rows) {
        if (row.action === "add" && "name3" in row) {
          const base = slug(row.name3.en || row.name3.ru);
          items.push({
            code: base,
            name: row.name3,
            attrs: {},
            active: true,
            position: items.length * 10 + 10,
            used: false,
          });
        }
        if (row.action === "update" && "name3" in row) {
          const current = items.find((i) => i.code === row.code);
          if (current) {
            current.name = {
              ru: row.name3.ru || current.name.ru,
              uz: row.name3.uz || current.name.uz,
              en: row.name3.en || current.name.en,
            };
            if ("active" in row && typeof row.active === "boolean") current.active = row.active;
          }
        }
      }
      writeDictionaries({ ...state, [kind]: items });
    }
    return HttpResponse.json({
      applied,
      added: rows.filter((r) => r.action === "add").length,
      updated: rows.filter((r) => r.action === "update").length,
      unchanged: rows.filter((r) => r.action === "unchanged").length,
      failed,
      rows: rows.map(({ line, code, name, action, fields, errors }) => ({
        line,
        code,
        name,
        action,
        fields,
        errors,
      })),
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
