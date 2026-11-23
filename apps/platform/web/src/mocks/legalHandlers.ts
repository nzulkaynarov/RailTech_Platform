import { HttpResponse, http } from "msw";

import type {
  LegalAcceptance,
  LegalContent,
  LegalEditionDetail,
  LegalEditionRow,
  LegalEditionUpdate,
  LegalKind,
} from "../shared/api/generated/model";
import { failure } from "./adminUsers";
import { buildMe, readSession } from "./mockSession";

/**
 * Моки ДВ-5 (BFF, «Настройки · Оферта и политика»): правила как у ERP — один черновик на вид, опубликованное не правится,
 * публикация снимает прежнюю действующую, текст — на трёх языках. Состояние живёт в памяти страницы; демо-тексты короткие и
 * вымышленные. Права раздела `company.settings` проверяет BFF (тесты BFF), здесь — только сессия.
 */
interface Stored {
  id: number;
  kind: LegalKind;
  label: string;
  status: "draft" | "current" | "retired";
  createdAt: string;
  publishedAt?: string;
  publishedBy?: string;
  retiredAt?: string;
  content: LegalContent;
}

const text = (ru: string, uz: string, en: string) => ({ ru, uz, en });

function content(kind: LegalKind): LegalContent {
  const privacy = kind === "privacy";
  const sections = (
    privacy
      ? [
          ["Общие положения", "Umumiy qoidalar", "General provisions"],
          [
            "Какие данные мы обрабатываем",
            "Qanday maʼlumotlarga işlov beramiz",
            "What data we process",
          ],
          ["Цели и основания", "Maqsad va asoslar", "Purposes and grounds"],
          ["Права субъекта данных", "Maʼlumotlar subyektining huquqlari", "Data subject rights"],
        ]
      : [
          ["Предмет и акцепт", "Predmet va aksept", "Subject and acceptance"],
          ["Доступ по приглашению", "Taklif orqali kiriş", "Access by invitation"],
          ["Действия в Кабинете", "Kabinetdagi harakatlar", "Actions in the Cabinet"],
          ["Новая редакция", "Yangi tahrir", "New edition"],
        ]
  ).map(([ru = "", uz = "", en = ""], index) => ({
    title: text(
      `${String(index + 1)}. ${ru}`,
      `${String(index + 1)}. ${uz}`,
      `${String(index + 1)}. ${en}`,
    ),
    body: text(
      `Оператор {{company.name}}, ИНН {{company.inn}}, действует в пределах закона.\n— запись о действии хранится в журнале;\n— контакт может написать на {{company.support_email}}.`,
      `Operator {{company.name}}, STIR {{company.inn}}, qonun doirasida harakat qiladi.\n— harakat haqidagi yozuv jurnalda saqlanadi;\n— kontakt {{company.support_email}} manziliga yoza oladi.`,
      `The operator {{company.name}}, tax ID {{company.inn}}, acts within the law.\n— a record of the action is kept in the log;\n— the contact can write to {{company.support_email}}.`,
    ),
  }));
  return {
    title: privacy
      ? text(
          "Политика обработки персональных данных в Кабинете",
          "Kabinetda şaxsga doir maʼlumotlarga işlov beriş siyosati",
          "Personal data processing policy for the Cabinet",
        )
      : text(
          "Условия использования Кабинета (оферта)",
          "Kabinetdan foydalaniş şartlari (oferta)",
          "Cabinet terms of use (offer)",
        ),
    lead: text(
      "Как {{company.name}} работает с данными представителей клиентов.",
      "{{company.name}} mijoz vakillarining maʼlumotlari bilan qanday işlaydi.",
      "How {{company.name}} handles data of client representatives.",
    ),
    sections,
  };
}

const render = (value: LegalContent): LegalContent => {
  const fill = (s: string) =>
    s
      .replaceAll("{{company.name}}", "ООО «РейлТех Демо»")
      .replaceAll("{{company.inn}}", "300000000")
      .replaceAll("{{company.support_email}}", "support@demo.example");
  const lang = (t: { ru: string; uz: string; en: string }) => ({
    ru: fill(t.ru),
    uz: fill(t.uz),
    en: fill(t.en),
  });
  return {
    title: lang(value.title),
    lead: lang(value.lead),
    sections: value.sections.map((s) => ({ title: lang(s.title), body: lang(s.body) })),
  };
};

let editions: Stored[] = [];
let next = 10;

function seed(): void {
  editions = [
    {
      id: 1,
      kind: "privacy",
      label: "2026-08-01",
      status: "retired",
      createdAt: "2026-07-30T09:00:00Z",
      publishedAt: "2026-08-01T09:00:00Z",
      publishedBy: "Администратор Демо",
      retiredAt: "2026-11-23T09:00:00Z",
      content: content("privacy"),
    },
    {
      id: 2,
      kind: "privacy",
      label: "2026-11-23",
      status: "current",
      createdAt: "2026-11-22T09:00:00Z",
      publishedAt: "2026-11-23T09:00:00Z",
      publishedBy: "Директор Демо",
      content: content("privacy"),
    },
    {
      id: 3,
      kind: "terms",
      label: "2026-11-23",
      status: "draft",
      createdAt: "2026-11-23T08:00:00Z",
      content: content("terms"),
    },
  ];
  next = 10;
}
seed();

/** Тесты и снимки: вернуть исходное состояние. */
export function resetLegalMock(): void {
  seed();
}

const COUNTS: Record<number, number> = { 1: 12, 2: 3, 3: 0 };

function row(e: Stored): LegalEditionRow {
  return {
    id: String(e.id),
    kind: e.kind,
    label: e.label,
    status: e.status,
    created_at: e.createdAt,
    ...(e.publishedAt ? { published_at: e.publishedAt } : {}),
    ...(e.publishedBy ? { published_by: e.publishedBy } : {}),
    ...(e.retiredAt ? { retired_at: e.retiredAt } : {}),
    acceptances_count: COUNTS[e.id] ?? 0,
  };
}
const detail = (e: Stored): LegalEditionDetail => ({
  ...row(e),
  content: e.content,
  rendered: render(e.content),
});

const ACCEPTANCES: LegalAcceptance[] = [
  [
    "Азамат Каримов",
    "a.karimov@toshlog.example",
    "ООО «Тошкент Логистик»",
    "ru",
    2,
    "2026-11-23T11:20:00Z",
  ],
  [
    "Дилноза Рахимова",
    "d.rahimova@vodokanal.example",
    "АО «Водоканал»",
    "uz",
    2,
    "2026-11-23T10:05:00Z",
  ],
  ["Sardor Aliyev", "s.aliyev@silk.example", "Silk Road Trading", "en", 2, "2026-11-23T09:40:00Z"],
  [
    "Азамат Каримов",
    "a.karimov@toshlog.example",
    "ООО «Тошкент Логистик»",
    "ru",
    1,
    "2026-08-04T08:15:00Z",
  ],
].map(([name, email, company, language, edition, at], index) => ({
  id: String(100 + index),
  accepted_at: String(at),
  kind: "privacy" as const,
  edition: edition === 2 ? "2026-11-23" : "2026-08-01",
  edition_id: String(edition),
  language: language as "ru" | "uz" | "en",
  auth_method: "magic_link",
  contact: { id: String(10 + index), name: String(name), email: String(email) },
  company: { id: String(20 + index), name: String(company) },
}));

const unauthorized = () => failure(401, "SESSION_EXPIRED", "Сессия истекла");
const notFound = () => failure(404, "NOT_FOUND", "Не найдено.", "erp");
const conflict = (reason: string, message: string) =>
  failure(409, "CONFLICT", message, "erp", { reason });
const find = (id: unknown) => editions.find((e) => e.id === Number(id));

function validContent(value: LegalContent | undefined): boolean {
  if (!value || value.sections.length === 0) return false;
  const full = (t: { ru: string; uz: string; en: string }) =>
    Boolean(t.ru.trim() && t.uz.trim() && t.en.trim());
  return full(value.title) && value.sections.every((s) => full(s.title) && full(s.body));
}

export const legalHandlers = [
  http.get("*/admin/legal-editions", () => {
    if (!readSession()) return unauthorized();
    return HttpResponse.json({ items: editions.map(row) });
  }),
  http.post("*/admin/legal-editions", async ({ request }) => {
    if (!readSession()) return unauthorized();
    const { kind } = (await request.json()) as { kind: LegalKind };
    if (editions.some((e) => e.kind === kind && e.status === "draft")) {
      return conflict(
        "legal_draft_exists",
        "Черновик этого документа уже есть: откройте его и правьте.",
      );
    }
    const source = editions.find((e) => e.kind === kind && e.status === "current");
    const created: Stored = {
      id: next++,
      kind,
      label: "2026-12-01",
      status: "draft",
      createdAt: new Date().toISOString(),
      content: structuredClone(source?.content ?? content(kind)),
    };
    editions.push(created);
    return HttpResponse.json(detail(created), { status: 201 });
  }),
  http.get("*/admin/legal-editions/:id", ({ params }) => {
    if (!readSession()) return unauthorized();
    const found = find(params["id"]);
    return found ? HttpResponse.json(detail(found)) : notFound();
  }),
  http.patch("*/admin/legal-editions/:id", async ({ params, request }) => {
    if (!readSession()) return unauthorized();
    const found = find(params["id"]);
    if (!found) return notFound();
    if (found.status !== "draft")
      return conflict("legal_edition_published", "Редакция уже опубликована и не меняется.");
    const input = (await request.json()) as LegalEditionUpdate;
    if (input.content !== undefined) {
      if (!validContent(input.content)) {
        return failure(422, "VALIDATION_FAILED", "Проверьте заполнение полей.", "erp", {
          reason: "validation_error",
        });
      }
      found.content = input.content;
    }
    if (input.label !== undefined) {
      if (
        editions.some((e) => e.id !== found.id && e.kind === found.kind && e.label === input.label)
      ) {
        return conflict("legal_label_taken", "Такое название уже есть.");
      }
      found.label = input.label;
    }
    return HttpResponse.json(detail(found));
  }),
  http.delete("*/admin/legal-editions/:id", ({ params }) => {
    if (!readSession()) return unauthorized();
    const found = find(params["id"]);
    if (!found) return notFound();
    if (found.status !== "draft")
      return conflict("legal_edition_published", "Редакция уже опубликована и не меняется.");
    editions = editions.filter((e) => e.id !== found.id);
    return new HttpResponse(null, { status: 204 });
  }),
  http.post("*/admin/legal-editions/:id/publish", ({ params }) => {
    if (!readSession()) return unauthorized();
    const found = find(params["id"]);
    if (!found) return notFound();
    if (found.status !== "draft")
      return conflict("legal_edition_published", "Редакция уже опубликована и не меняется.");
    const now = new Date().toISOString();
    for (const old of editions) {
      if (old.kind === found.kind && old.status === "current") {
        old.status = "retired";
        old.retiredAt = now;
      }
    }
    found.status = "current";
    found.publishedAt = now;
    const session = readSession();
    found.publishedBy = (session ? buildMe(session)?.name : undefined) ?? "Администратор";
    return HttpResponse.json(detail(found));
  }),
  http.get("*/admin/legal-acceptances", ({ request }) => {
    if (!readSession()) return unauthorized();
    const url = new URL(request.url);
    const edition = url.searchParams.get("edition");
    const q = (url.searchParams.get("q") ?? "").toLowerCase();
    const items = ACCEPTANCES.filter(
      (a) =>
        (!edition || a.edition_id === edition) &&
        (!q || `${a.contact.name} ${a.contact.email} ${a.company.name}`.toLowerCase().includes(q)),
    );
    return HttpResponse.json({ items, total: items.length, page: 1, page_size: 100 });
  }),
];
