import { HttpResponse, http } from "msw";

import type {
  ProjectActActionIn,
  ProjectContractActionIn,
  ProjectJournalEntry,
  ProjectPage,
  ProjectRow,
  ProjectStage,
} from "../shared/api/generated/model";
import {
  type MockDocLinkKind,
  actDelivered,
  DELIVERY_FROM,
  MOCK_STAFF_ID,
  type ProjectState,
  findProject,
  isDone,
  numberOf,
  ownsDocument,
  problemsOf,
  readDocLinks,
  readProjects,
  revokeDocLinks,
  sendBlockerOf,
  stepOf,
  templateOf,
  termOf,
  toCard,
  toRow,
  writeProject,
} from "./fixtures/projects";
import { companyToday } from "../shared/lib/dates";
import { buildMe, readSession } from "./mockSession";
import { markOfName } from "./doNotWorkMarks";

/**
 * Моки EDS · Проекты (D2-5, BFF 0.26.0). Права — как в BFF: чтение — `eds.projects` (менеджер, снабженец, гл. инженер, директор,
 * бухгалтер), действия — `eds.projects` полный (директор и бухгалтер). Переходы статусов договора и акта, сигнатура и размер
 * скана, ошибки и подкоды — как у ERP, чтобы экран и e2e видели настоящее поведение.
 */
type Level = "read" | "full";

function failure(
  status: number,
  code: string,
  message: string,
  source: "bff" | "erp" = "bff",
  details?: Record<string, unknown>,
) {
  return HttpResponse.json({ code, message, source, ...(details ? { details } : {}) }, { status });
}

function guard(need: Level) {
  const session = readSession();
  if (!session) return { error: failure(401, "SESSION_EXPIRED", "Сессия истекла") };
  // Права операций — по объединению ролей, а не по активной роли («вид»), как в BFF.
  const me = buildMe(session);
  const level = me?.resources["eds.projects"];
  if (!level || (need === "full" && level !== "full")) {
    return {
      error: failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.", "bff", {
        resource: "eds.projects",
        need,
      }),
    };
  }
  return {
    writer: level === "full",
    // Отметки доставки (L0-1) — право ERP `fulfillment.manage`: раздел «Склад» полный.
    marker: me.resources["erp.stock"] === "full",
    // ДОК-10: решает по отступлению держатель зоны «Право» (раздел `eds.visa.legal`) или администратор
    approver: me.resources["eds.visa.legal"] === "full" || me.resources["admin"] === "full",
    staffId: MOCK_STAFF_ID[session.userId],
  };
}

const notFound = () =>
  failure(404, "NOT_FOUND", "Проект не найден.", "erp", { backend_status: 404 });

const conflict = (reason: string, message: string) =>
  failure(409, "CONFLICT", message, "erp", { backend_status: 409, reason });

function refOf(request: Request): string {
  const path = new URL(request.url).pathname;
  const tail = path.slice(path.indexOf("/eds/projects/") + "/eds/projects/".length);
  return tail.split("/")[0] ?? "";
}

const now = () => new Date().toISOString();

/**
 * Режим «у компании есть утверждённые шаблоны договоров» (ДОК-10): `localStorage["rt-pf-mock-contract-template"] = "on"`
 * до формирования проекта. Без ключа проект собирается прежним путём (переходный режим ERP), и сценарии прежних экранов
 * не меняются.
 */
function templateMode(): boolean {
  try {
    return window.localStorage.getItem("rt-pf-mock-contract-template") === "on";
  } catch {
    return false;
  }
}
const ACTOR = "Демо Бухгалтеров";

function logged(
  p: ProjectState,
  code: string,
  document: "contract" | "act" | "project",
  number: string,
  text: string,
  reason = "",
  onBehalf: ProjectJournalEntry["on_behalf"] = null,
): ProjectState {
  return {
    ...p,
    journal: [
      { at: now(), code, text, actor_name: ACTOR, document, number, reason, on_behalf: onBehalf },
      ...p.journal,
    ],
  };
}

// --- договор ------------------------------------------------------------------------------------------------

const TRANSITIONS: Record<
  Exclude<
    ProjectContractActionIn["action"],
    | "sign_ours"
    | "request_deviation"
    | "decide_deviation"
    | "decline_renewal"
    | "restore_renewal"
    | "renew"
    | "send_new_edition"
    | "mark_signed"
    | "remark_vote"
    | "remark_decide"
  >,
  { from: string[]; to: string; code: string; text: string }
> = {
  send_to_client: {
    from: ["project:unsent"],
    to: "project",
    code: "contract.sent_to_client",
    text: "Проект договора отправлен клиенту на согласование",
  },
  client_agreed: {
    from: ["project:sent"],
    to: "client_agreed",
    code: "contract.client_agreed",
    text: "Редакция договора согласована клиентом",
  },
  reject: {
    from: ["project:sent", "client_agreed", "issued_at_operator"],
    to: "rejected",
    code: "contract.rejected",
    text: "Договор отклонён клиентом",
  },
  revise: {
    from: ["rejected"],
    to: "project",
    code: "contract.revised",
    text: "Проект договора возвращён в работу",
  },
  mark_issued: {
    from: ["client_agreed"],
    to: "issued_at_operator",
    code: "contract.issued_external",
    text: "Договор выставлен в ЭДО",
  },
};

/** Подписан (скан или заметка): ERP закрывает сделку как выигранную и создаёт черновик счёта на предоплату (D2-4 его выставит). */
function signed(
  p: ProjectState,
  ok: { writer: boolean; marker: boolean; approver: boolean },
  code: string,
  text: string,
  note: string,
  hasScan = false,
): Response {
  const c = p.contract;
  if (!c) return notFound();
  const draft = {
    id: 5000 + p.id,
    number: `СЧ-${String(p.year)}/${String(p.id).padStart(3, "0")}`,
    status: "to_issue" as const,
    total: p.total,
    paid: { amount: "0.00", currency: "UZS" },
    balance_due: p.total,
    issued_at: null,
    due_date: null,
    has_pdf: false,
  };
  const next = logged(
    {
      ...p,
      invoices: p.invoices.length > 0 ? p.invoices : [draft],
      contract: { ...c, status: "signed", signed_at: now(), has_scan: hasScan },
    },
    code,
    "contract",
    c.number,
    text,
    note,
  );
  writeProject(next);
  return HttpResponse.json(toCard(next, ok.writer, ok.marker, ok.approver));
}

/** ДП-1: ответ «Согласен» / «Не согласен» и решение директора; все согласны — редакция контрагента принята. */
function remarkAnswer(
  p: ProjectState,
  body: ProjectContractActionIn,
  ok: { writer: boolean; marker: boolean; approver: boolean },
): Response {
  const c = p.contract;
  const remark = c?.remark;
  if (!c || !remark || c.status !== "project") {
    return conflict("remark_not_open", "Замечаний на согласовании нет.");
  }
  if (body.action === "remark_vote") {
    if (body.approve === false && !body.text?.trim()) {
      return failure(422, "VALIDATION_FAILED", "Проверьте заполнение полей.", "bff", {
        fields: ["text"],
      });
    }
    const me = { id: 1, name: "Вы" };
    const votes = [
      ...remark.votes.filter((v) => v.user.id !== me.id),
      { user: me, agree: body.approve === true, comment: (body.text ?? "").trim(), at: now() },
    ];
    const awaiting = (c.remark_awaiting ?? []).filter((person) => person.id !== me.id);
    const accepted = awaiting.length === 0 && votes.every((v) => v.agree);
    const contract: typeof c = accepted
      ? {
          ...c,
          status: "client_agreed",
          remark: undefined,
          remark_awaiting: undefined,
          client_agreed_at: now(),
        }
      : { ...c, remark: { ...remark, votes }, remark_awaiting: awaiting };
    const next = logged(
      { ...p, contract },
      accepted ? "contract.remark_accepted" : "contract.remark_voted",
      "contract",
      c.number,
      accepted ? "Принята редакция контрагента" : "Ответ по замечаниям контрагента",
      (body.text ?? "").trim(),
    );
    writeProject(next);
    return HttpResponse.json(toCard(next, ok.writer, ok.marker, ok.approver));
  }
  if (body.approve === false && !body.text?.trim()) {
    return failure(422, "VALIDATION_FAILED", "Проверьте заполнение полей.", "bff", {
      fields: ["text"],
    });
  }
  const accepted = body.approve === true;
  const contract: typeof c = accepted
    ? {
        ...c,
        status: "client_agreed",
        remark: undefined,
        remark_awaiting: undefined,
        client_agreed_at: now(),
      }
    : { ...c, remark: undefined, remark_awaiting: undefined };
  const next = logged(
    { ...p, contract },
    accepted ? "contract.remark_accepted" : "contract.remark_countered",
    "contract",
    c.number,
    accepted ? "Принята редакция контрагента" : "Ответ контрагенту: наша редакция",
    (body.text ?? "").trim(),
  );
  writeProject(next);
  return HttpResponse.json(toCard(next, ok.writer, ok.marker, ok.approver));
}

/** ДС-1: отказ от продления и продление соглашением — по факту подписанного договора. */
function termAction(
  p: ProjectState,
  action: "decline_renewal" | "restore_renewal" | "renew",
): Response {
  const c = p.contract;
  if (!c || termOf(c, true) === null) return conflict("term_not_set", "У договора ещё нет срока.");
  const contract: typeof c =
    action === "decline_renewal"
      ? { ...c, term_declined_by: "company" }
      : action === "restore_renewal"
        ? { ...c, term_declined_by: undefined }
        : {
            ...c,
            term_declined_by: undefined,
            term_until: `${String(Number((c.signed_at ?? "").slice(0, 4)) + 1)}-12-31`,
          };
  const next = logged(
    { ...p, contract },
    action === "decline_renewal"
      ? "contract.renewal_declined"
      : action === "restore_renewal"
        ? "contract.renewal_restored"
        : "contract.term_renewed_by_agreement",
    "contract",
    c.number,
    action === "decline_renewal"
      ? "Отказ от продления договора"
      : action === "restore_renewal"
        ? "Отказ от продления снят"
        : "Договор продлён по соглашению",
    "",
  );
  writeProject(next);
  return HttpResponse.json(toCard(next, true, true, false));
}

/** Наша подпись, заявка на отступление и решение «Право»; после подписи без помех договор уходит в Кабинет сам. */
function templateAction(
  p: ProjectState,
  body: ProjectContractActionIn,
  ok: { writer: boolean; marker: boolean; approver: boolean },
): Response {
  const c = p.contract;
  const tpl = c?.template;
  if (!c || !tpl) return conflict("contract_not_from_template", "Договор собран не по шаблону.");
  if (c.sent_to_client) return conflict("contract_already_sent", "Договор уже ушёл клиенту.");
  const decided = body.approve === true ? "approved" : "rejected";
  let step: { template: typeof tpl; code: string; label: string };
  if (body.action === "sign_ours") {
    if (tpl.signed_ours_at) {
      return conflict("contract_already_signed_by_us", "Договор уже подписан от компании.");
    }
    step = {
      template: { ...tpl, signed_ours_at: now() },
      code: "contract.signed_by_us",
      label: "Договор подписан от компании до отправки",
    };
  } else if (body.action === "request_deviation") {
    if (!body.text?.trim()) {
      return failure(422, "VALIDATION_FAILED", "Проверьте заполнение полей.", "bff", {
        fields: ["text"],
      });
    }
    step = {
      template: { ...tpl, deviation: "requested", deviation_text: body.text.trim() },
      code: "contract.deviation_requested",
      label: "Запрошено отступление от шаблона договора",
    };
  } else {
    if (!ok.approver) {
      return failure(403, "FORBIDDEN", "Действие не положено вашей роли.", "erp", {
        backend_status: 403,
      });
    }
    step = {
      template: { ...tpl, deviation: decided },
      code: `contract.deviation_${decided}`,
      label: `Отступление от шаблона ${decided === "approved" ? "одобрено" : "отклонено"}`,
    };
  }
  let contract: typeof c = { ...c, template: step.template };
  // Авто-отправка: отступления нет (виз нет) и ничто не мешает.
  const free = templateOf(contract, true, ok.approver);
  if (free && !free.visas_required && sendBlockerOf(contract) === null) {
    contract = { ...contract, sent_to_client: true };
  }
  const next = logged(
    { ...p, contract },
    step.code,
    "contract",
    c.number,
    step.label,
    step.template.deviation_text,
  );
  writeProject(next);
  return HttpResponse.json(toCard(next, ok.writer, ok.marker, ok.approver));
}

function stateOf(p: ProjectState): string {
  const c = p.contract;
  if (!c) return "";
  return c.status === "project" ? (c.sent_to_client ? "project:sent" : "project:unsent") : c.status;
}

/** Сигнатура скана: PDF, JPG, PNG, WEBP (как проверяет ERP); пустой файл и чужой тип — `scan_invalid`. */
async function scanVerdict(request: Request): Promise<"ok" | "invalid" | "missing" | "large"> {
  // Файл из multipart без `request.formData()`: в jsdom (vitest) разбор форм в Node не знает чужой `File`,
  // а мок работает и там, и в браузере. Тело читается как latin1: байты и смещения совпадают.
  const boundary = /boundary=([^;]+)/.exec(request.headers.get("content-type") ?? "")?.[1];
  if (!boundary) return "missing";
  const raw = new Uint8Array(await request.arrayBuffer());
  if (raw.length > 20 * 1024 * 1024 + 1024) return "large";
  const text = Array.from(raw, (byte) => String.fromCharCode(byte)).join("");
  for (const part of text.split(`--${boundary}`)) {
    const split = part.indexOf("\r\n\r\n");
    if (split < 0) continue;
    const head = part.slice(0, split);
    const name = /filename="([^"]*)"/.exec(head)?.[1];
    if (name === undefined || !/name="file"/.test(head)) continue;
    const body = part.slice(split + 4).replace(/\r\n$/, "");
    if (body.length > 20 * 1024 * 1024) return "large";
    if (body.length === 0) return "invalid";
    const lower = name.toLowerCase();
    const pdf = body.startsWith("%PDF") && lower.endsWith(".pdf");
    const png = body.startsWith("\x89PNG") && lower.endsWith(".png");
    const jpg = body.startsWith("\xff\xd8\xff") && /\.jpe?g$/.test(lower);
    const webp = body.startsWith("RIFF") && body.slice(8, 12) === "WEBP" && lower.endsWith(".webp");
    return pdf || png || jpg || webp ? "ok" : "invalid";
  }
  return "missing";
}

function scanFailure(verdict: "invalid" | "missing" | "large") {
  if (verdict === "large") {
    return failure(413, "PAYLOAD_TOO_LARGE", "Скан больше 20 МБ.", "bff", {
      max_bytes: 20 * 1024 * 1024,
    });
  }
  const reason = verdict === "missing" ? "scan_required" : "scan_invalid";
  return failure(422, "VALIDATION_FAILED", "Проверьте заполнение полей.", "erp", {
    backend_status: 400,
    backend_code: reason.toUpperCase(),
    reason,
    fields: ["file"],
  });
}

/** Текстовые поля и имя файла формы multipart (без `request.formData()` — см. `scanVerdict`). */
async function multipartFields(
  request: Request,
): Promise<Record<string, string> & { fileName?: string }> {
  const boundary = /boundary=([^;]+)/.exec(request.headers.get("content-type") ?? "")?.[1];
  const out: Record<string, string> & { fileName?: string } = {};
  if (!boundary) return out;
  const raw = new Uint8Array(await request.arrayBuffer());
  const text = new TextDecoder().decode(raw);
  for (const part of text.split(`--${boundary}`)) {
    const split = part.indexOf("\r\n\r\n");
    if (split < 0) continue;
    const head = part.slice(0, split);
    const name = /name="([^"]*)"/.exec(head)?.[1];
    if (!name) continue;
    const file = /filename="([^"]*)"/.exec(head)?.[1];
    if (file !== undefined) {
      if (file) out.fileName = file;
      continue;
    }
    out[name] = part.slice(split + 4).replace(/\r\n$/, "");
  }
  return out;
}

function fieldFailure(reason: string, field: string, message: string) {
  return failure(422, "VALIDATION_FAILED", message, "erp", {
    backend_status: 400,
    backend_code: reason.toUpperCase(),
    reason,
    fields: [field],
  });
}

// --- обработчики --------------------------------------------------------------------------------------------

const STEP_ORDER = ["CONTRACT", "PAYMENT", "DONE"];
/** Порядок «щелчком по шапке» (Х-15), как у ERP: белый список полей, `-` — по убыванию, пустые — в конце. */
const SORT_FIELDS: Record<string, (row: ProjectRow) => string | number | null> = {
  number: (row) => row.number,
  client: (row) => row.client_name,
  step: (row) => STEP_ORDER.indexOf(row.step),
  due_date: (row) => row.due_date,
  responsible: (row) => row.responsible?.name ?? null,
};

function sortedBy(rows: ProjectRow[], sort: string | null): ProjectRow[] {
  const desc = sort?.startsWith("-") ?? false;
  const value = SORT_FIELDS[desc ? (sort ?? "").slice(1) : (sort ?? "")];
  if (!value) return rows;
  const filled = rows.filter((row) => value(row) !== null && value(row) !== "");
  const empty = rows.filter((row) => value(row) === null || value(row) === "");
  filled.sort((a, b) => {
    const x = value(a);
    const y = value(b);
    const result =
      typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
    return desc ? -result : result;
  });
  return [...filled, ...empty];
}

export const edsProjectsHandlers = [
  http.get("*/eds/projects", ({ request }) => {
    const ok = guard("read");
    if (ok.error) return ok.error;
    const url = new URL(request.url);
    const mine = url.searchParams.get("mine") === "true";
    const problems = url.searchParams.get("problems") === "true";
    const step = url.searchParams.get("step") as ProjectStage | null;
    const q = (url.searchParams.get("q") ?? "").trim().toLowerCase();
    const limit = Number(url.searchParams.get("limit") ?? 25);
    const offset = Number(url.searchParams.get("offset") ?? 0);
    const found = [...readProjects()]
      .sort((a, b) => b.created_at.localeCompare(a.created_at))
      .filter((p) => !mine || p.manager.id === ok.staffId)
      .filter((p) => !problems || problemsOf(p).length > 0)
      .filter((p) => !step || stepOf(p) === step)
      .filter(
        (p) =>
          !q ||
          [p.title, p.client, p.contract?.number, p.quote.number, numberOf(p)]
            .filter(Boolean)
            .some((v) => String(v).toLowerCase().includes(q)),
      );
    const rows = sortedBy(found.map(toRow), url.searchParams.get("sort"));
    const page: ProjectPage = {
      items: rows.slice(offset, offset + limit),
      total: found.length,
      offset,
      limit,
    };
    return HttpResponse.json(page);
  }),

  http.get("*/eds/projects/:ref", ({ request }) => {
    const ok = guard("read");
    if (ok.error) return ok.error;
    const project = findProject(refOf(request));
    return project
      ? HttpResponse.json({
          ...toCard(project, ok.writer, ok.marker, ok.approver),
          do_not_work: markOfName(project.client),
        })
      : notFound();
  }),

  http.post("*/eds/projects/:ref/contract/draft", ({ request }) => {
    const ok = guard("full");
    if (ok.error) return ok.error;
    const p = findProject(refOf(request));
    if (!p) return notFound();
    if (p.contract) return conflict("contract_exists", "Проект договора уже сформирован.");
    const number = `ДОГ-${String(p.year)}/${String(p.id).padStart(3, "0")}`;
    const next = logged(
      {
        ...p,
        contract: {
          id: 900 + p.id,
          number,
          status: "project",
          sent_to_client: false,
          total: p.total,
          created_at: now(),
          client_agreed_at: null,
          signed_at: null,
          has_scan: false,
          visas: "none",
          // ДОК-10: проект собирается из утверждённого шаблона вида контрагента (шаблон по умолчанию из настроек)
          ...(templateMode()
            ? {
                template: {
                  id: 1,
                  name: "Договор с клиентом · поставка",
                  edition: 3,
                  deviation: "none" as const,
                  deviation_text: "",
                  signed_ours_at: null,
                },
              }
            : {}),
        },
      },
      "contract.created",
      "contract",
      number,
      "Создан проект договора",
    );
    writeProject(next);
    return HttpResponse.json(toCard(next, ok.writer, ok.marker, ok.approver), { status: 201 });
  }),

  http.post("*/eds/projects/:ref/contract", async ({ request }) => {
    // Решение по отступлению принимает держатель «Право» (раздел `eds.visa.legal`); «Проекты» у него — чтение (как BFF).
    const ok = guard("read");
    if (ok.error) return ok.error;
    const p = findProject(refOf(request));
    if (!p?.contract) return notFound();
    const body = (await request.json()) as ProjectContractActionIn;
    // ДП-1: ответ на замечания даёт и сотрудник с «Проекты» — чтение (кто вправе, решает ERP)
    const answers = body.action === "remark_vote" || body.action === "remark_decide";
    if (!ok.writer && !(body.action === "decide_deviation" && ok.approver) && !answers) {
      return failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.", "bff", {
        resource: "eds.projects",
        need: "full",
      });
    }
    if (body.action === "reject" && !body.reason?.trim()) {
      return failure(422, "VALIDATION_FAILED", "Проверьте заполнение полей.", "bff", {
        fields: ["reason"],
      });
    }
    // A2: «Согласован клиентом» — канал и лицо со стороны клиента обязательны (BFF отклоняет до ERP).
    if (body.action === "client_agreed" && (!body.channel || !body.counterparty_person?.trim())) {
      return failure(422, "VALIDATION_FAILED", "Проверьте заполнение полей.", "bff", {
        fields: [body.channel ? "counterparty_person" : "channel"],
      });
    }
    if (
      body.action === "sign_ours" ||
      body.action === "request_deviation" ||
      body.action === "decide_deviation"
    ) {
      return templateAction(p, body, ok);
    }
    if (body.action === "mark_signed") {
      if (!body.note?.trim()) {
        return failure(422, "VALIDATION_FAILED", "Проверьте заполнение полей.", "bff", {
          fields: ["note"],
        });
      }
      if (stateOf(p) !== "client_agreed" && stateOf(p) !== "issued_at_operator") {
        return conflict("contract_transition_not_allowed", "Договор сейчас в другом статусе.");
      }
      return signed(
        p,
        ok,
        "contract.marked_signed",
        "Договор отмечен подписанным",
        body.note.trim(),
      );
    }
    if (body.action === "remark_vote" || body.action === "remark_decide") {
      return remarkAnswer(p, body, ok);
    }
    if (
      body.action === "decline_renewal" ||
      body.action === "restore_renewal" ||
      body.action === "renew"
    ) {
      return termAction(p, body.action);
    }
    if (body.action === "send_new_edition") {
      return conflict("term_no_new_edition", "Новой утверждённой редакции шаблона нет.");
    }
    const rule = TRANSITIONS[body.action];
    // Одна проверка ERP (`contract_flow.send_blocker`): правила шаблона (ДОК-10) отвечают своим кодом, визы (Х-1) — 409
    // `CONTRACT_VISAS_REQUIRED`.
    const blocker = body.action === "send_to_client" ? sendBlockerOf(p.contract) : null;
    if (blocker) {
      return blocker.code.startsWith("CONTRACT_")
        ? conflict(blocker.code.toLowerCase(), blocker.message)
        : conflict(
            "contract_visas_required",
            "Договор нельзя отправить клиенту: сначала нужны визы.",
          );
    }
    if (!rule.from.includes(stateOf(p))) {
      return conflict("contract_transition_not_allowed", "Договор сейчас в другом статусе.");
    }
    const c = p.contract;
    const sent = body.action === "send_to_client" || (body.action !== "revise" && c.sent_to_client);
    const next = logged(
      {
        ...p,
        contract: {
          ...c,
          status: rule.to as typeof c.status,
          sent_to_client: sent,
          client_agreed_at:
            body.action === "client_agreed"
              ? now()
              : body.action === "revise"
                ? null
                : c.client_agreed_at,
        },
      },
      rule.code,
      "contract",
      c.number,
      rule.text,
      (body.reason ?? body.note ?? "").trim(),
      body.action === "client_agreed" && body.channel
        ? { channel: body.channel, counterparty_person: (body.counterparty_person ?? "").trim() }
        : null,
    );
    writeProject(next);
    return HttpResponse.json(toCard(next, ok.writer, ok.marker, ok.approver));
  }),

  // «На подпись» (SIGN-4): у договора открывает круг виз бухгалтера и юриста; сколько виз собрано, решают они в EDS.
  http.post("*/eds/projects/:ref/signing", async ({ request }) => {
    const ok = guard("full");
    if (ok.error) return ok.error;
    const p = findProject(refOf(request));
    if (!p) return notFound();
    const body = (await request.json()) as { kind: string };
    const c = p.contract;
    const next =
      body.kind === "contract" && c && c.visas === "none"
        ? { ...p, contract: { ...c, visas: "pending" as const } }
        : p;
    writeProject(next);
    return HttpResponse.json(toCard(next, ok.writer, ok.marker));
  }),

  http.post("*/eds/projects/:ref/contract/scan", async ({ request }) => {
    const ok = guard("full");
    if (ok.error) return ok.error;
    const p = findProject(refOf(request));
    if (!p?.contract) return notFound();
    if (stateOf(p) !== "client_agreed" && stateOf(p) !== "issued_at_operator") {
      return conflict("contract_transition_not_allowed", "Договор сейчас в другом статусе.");
    }
    const verdict = await scanVerdict(request.clone());
    if (verdict !== "ok") return scanFailure(verdict);
    return signed(
      p,
      ok,
      "contract.scan_attached",
      "Прикреплён скан подписанного договора",
      "",
      true,
    );
  }),

  // --- акт --------------------------------------------------------------------------------------------------

  http.post("*/eds/projects/:ref/act", async ({ request }) => {
    const ok = guard("full");
    if (ok.error) return ok.error;
    const p = findProject(refOf(request));
    if (!p) return notFound();
    const body = (await request.json()) as ProjectActActionIn;
    if (body.action === "return" && !body.reason?.trim()) {
      return failure(422, "VALIDATION_FAILED", "Проверьте заполнение полей.", "bff", {
        fields: ["reason"],
      });
    }
    if (body.action === "issue") {
      if (p.act) return conflict("act_already_exists", "Акт по этому проекту уже есть.");
      if (!p.invoices.some((i) => ["issued", "partial", "paid", "overdue"].includes(i.status))) {
        return conflict(
          "no_invoice",
          "Акт можно выпустить по выставленному счёту: счёта пока нет.",
        );
      }
      if (!actDelivered(p)) {
        return conflict("not_delivered", "Акт выпускается после доставки: товар ещё не доставлен.");
      }
      const number = `АКТ-${String(p.year)}/${String(p.id).padStart(3, "0")}`;
      const next = logged(
        {
          ...p,
          act: {
            id: 800 + p.id,
            number,
            status: "issued",
            total: p.total,
            issued_at: now().slice(0, 10),
            signed_at: null,
            rejection_reason: "",
            has_scan: false,
          },
        },
        "act.issued",
        "act",
        number,
        "Акт выпущен",
      );
      writeProject(next);
      return HttpResponse.json(toCard(next, ok.writer, ok.marker, ok.approver));
    }
    const a = p.act;
    if (!a) return notFound();
    if (body.action === "return") {
      if (a.status !== "issued")
        return conflict("act_sign_not_allowed", "Акт сейчас в другом статусе.");
      const reason = (body.reason ?? "").trim();
      const next = logged(
        { ...p, act: { ...a, status: "returned", rejection_reason: reason } },
        "act.rejected",
        "act",
        a.number,
        "Акт возвращён заказчиком",
        reason,
      );
      writeProject(next);
      return HttpResponse.json(toCard(next, ok.writer, ok.marker, ok.approver));
    }
    if (a.status !== "returned")
      return conflict("act_sign_not_allowed", "Акт сейчас в другом статусе.");
    const next = logged(
      { ...p, act: { ...a, status: "issued" } },
      "act.issued",
      "act",
      a.number,
      "Акт выпущен заново",
    );
    writeProject(next);
    return HttpResponse.json(toCard(next, ok.writer, ok.marker, ok.approver));
  }),

  http.post("*/eds/projects/:ref/act/scan", async ({ request }) => {
    const ok = guard("full");
    if (ok.error) return ok.error;
    const p = findProject(refOf(request));
    if (!p?.act) return notFound();
    if (p.act.status !== "issued") {
      return conflict("act_sign_not_allowed", "Акт сейчас в другом статусе.");
    }
    const verdict = await scanVerdict(request.clone());
    if (verdict !== "ok") return scanFailure(verdict);
    const moment = now();
    let next = logged(
      { ...p, act: { ...p.act, status: "signed", signed_at: moment, has_scan: true } },
      "act.scan_attached",
      "act",
      p.act.number,
      "Прикреплён скан подписанного акта",
    );
    // Акт подписан и все счета оплачены — проект «Выполнено» (одна запись в журнале).
    if (isDone(next)) {
      next = logged(next, "project.done", "project", "", "Проект выполнен");
    }
    writeProject(next);
    return HttpResponse.json(toCard(next, ok.writer, ok.marker, ok.approver));
  }),

  // --- доставка клиенту (L0-1) -------------------------------------------------------------------------------

  http.post("*/eds/projects/:ref/delivery", async ({ request }) => {
    const ok = guard("read");
    if (ok.error) return ok.error;
    const p = findProject(refOf(request));
    if (!p) return notFound();
    if (!ok.marker) {
      return failure(403, "FORBIDDEN", "Действие не положено вашей роли.", "erp", {
        backend_status: 403,
        backend_code: "ROLE_NOT_PERMITTED",
        reason: "role_not_permitted",
      });
    }
    const f = p.fulfillment;
    if (!f) {
      return conflict(
        "fulfillment_not_ready",
        "Исполнения по проекту ещё нет: оно появляется после договора.",
      );
    }
    const form = await multipartFields(request.clone());
    const action =
      form.action === "delivered"
        ? "delivered"
        : form.action === "in_transit"
          ? "in_transit"
          : null;
    const onDate = form.on_date ?? "";
    if (!action) return fieldFailure("delivery_action_invalid", "action", "Выберите отметку.");
    if (!/^\d{4}-\d{2}-\d{2}$/.test(onDate)) {
      return fieldFailure("delivery_date_invalid", "on_date", "Укажите дату.");
    }
    if (onDate > companyToday()) {
      return fieldFailure("delivery_date_in_future", "on_date", "Дата не может быть в будущем.");
    }
    if (!DELIVERY_FROM[action].includes(f.status ?? "")) {
      return conflict(
        "delivery_transition_not_allowed",
        "Доставка сейчас в другом статусе. Обновите страницу.",
      );
    }
    const at = `${onDate}T12:00:00+05:00`;
    const waybill = (form.waybill ?? "").trim();
    const delivered = action === "delivered";
    const lineStatus = delivered ? "delivered" : "in_transit";
    const next = logged(
      {
        ...p,
        fulfillment: {
          ...f,
          status: delivered ? "DELIVERED" : "IN_TRANSIT",
          status_name: delivered ? "Доставлено" : "В пути",
          shipped_at: f.shipped_at ?? at,
          delivered_at: delivered ? at : f.delivered_at,
          tracking_number: waybill || f.tracking_number,
          proof_name: form.fileName ?? f.proof_name,
        },
        lines: (p.lines ?? []).map((line) => ({ ...line, status: lineStatus })),
      },
      `project.delivery_${action}`,
      "project",
      "",
      delivered ? "Доставлено клиенту" : "Отправлено клиенту, в пути",
    );
    writeProject(next);
    return HttpResponse.json(toCard(next, ok.writer, ok.marker, ok.approver));
  }),

  http.get("*/eds/projects/:ref/delivery/proof", ({ request }) => {
    const ok = guard("read");
    if (ok.error) return ok.error;
    const p = findProject(refOf(request));
    if (!p?.fulfillment?.proof_name) return notFound();
    return new HttpResponse(new TextEncoder().encode("%PDF-1.4 demo\n"), {
      headers: {
        "Content-Type": "application/octet-stream",
        "Content-Disposition": 'attachment; filename="delivery-proof"',
        "X-Content-Type-Options": "nosniff",
      },
    });
  }),

  // --- ссылка клиента на документ в Кабинете (ДК-3б) -------------------------------------------------------

  // Видит и отзывает тот, кто отправляет документ (в мок-ролях — `eds.projects` полный); остальным список пуст.
  http.get("*/eds/projects/:ref/documents/:kind/:docId/client-links", ({ request, params }) => {
    const ok = guard("read");
    if (ok.error) return ok.error;
    const p = findProject(refOf(request));
    const kind = params["kind"] as MockDocLinkKind;
    const id = Number(params["docId"]);
    if (!p || !ownsDocument(p, kind, id)) return notFound();
    if (!ok.writer) return HttpResponse.json({ links: [], can_revoke: false });
    const links = readDocLinks(kind, id);
    return HttpResponse.json({ links, can_revoke: links.some((l) => l.state === "active") });
  }),

  http.post("*/eds/projects/:ref/documents/:kind/:docId/revoke-links", ({ request, params }) => {
    const ok = guard("read");
    if (ok.error) return ok.error;
    const p = findProject(refOf(request));
    const kind = params["kind"] as MockDocLinkKind;
    const id = Number(params["docId"]);
    if (!p || !ownsDocument(p, kind, id)) return notFound();
    if (!ok.writer) {
      return failure(403, "FORBIDDEN", "Действие не положено вашей роли.", "erp", {
        backend_status: 403,
      });
    }
    return HttpResponse.json({ links: revokeDocLinks(kind, id), can_revoke: false });
  }),

  // --- файлы ------------------------------------------------------------------------------------------------

  http.get("*/eds/projects/:ref/files/:kind/:docId", ({ request }) => {
    const ok = guard("read");
    if (ok.error) return ok.error;
    const p = findProject(refOf(request));
    if (!p) return notFound();
    const variant = new URL(request.url).searchParams.get("variant") ?? "pdf";
    const bytes = new TextEncoder().encode("%PDF-1.4 demo\n");
    return new HttpResponse(bytes, {
      headers: {
        "Content-Type": variant === "scan" ? "application/octet-stream" : "application/pdf",
        "Content-Disposition": `attachment; filename="${variant === "scan" ? "scan.pdf" : "document.pdf"}"`,
        "X-Content-Type-Options": "nosniff",
      },
    });
  }),
];
