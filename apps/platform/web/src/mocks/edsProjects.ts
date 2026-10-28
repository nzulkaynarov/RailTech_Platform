import { HttpResponse, http } from "msw";

import type {
  ProjectActActionIn,
  ProjectContractActionIn,
  ProjectPage,
  ProjectStage,
} from "../shared/api/generated/model";
import {
  MOCK_STAFF_ID,
  type ProjectState,
  findProject,
  isDone,
  numberOf,
  problemsOf,
  readProjects,
  stepOf,
  toCard,
  toRow,
  writeProject,
} from "./fixtures/projects";
import { buildMe, readSession } from "./mockSession";

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
  const me = buildMe({ ...session, activeRole: null });
  const level = me?.resources["eds.projects"];
  if (!level || (need === "full" && level !== "full")) {
    return {
      error: failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.", "bff", {
        resource: "eds.projects",
        need,
      }),
    };
  }
  return { writer: level === "full", staffId: MOCK_STAFF_ID[session.userId] };
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
const ACTOR = "Демо Бухгалтеров";

function logged(
  p: ProjectState,
  code: string,
  document: "contract" | "act" | "project",
  number: string,
  text: string,
  reason = "",
): ProjectState {
  return {
    ...p,
    journal: [{ at: now(), code, text, actor_name: ACTOR, document, number, reason }, ...p.journal],
  };
}

// --- договор ------------------------------------------------------------------------------------------------

const TRANSITIONS: Record<
  Exclude<ProjectContractActionIn["action"], never>,
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
    text: "Договор выставлен у оператора",
  },
};

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

// --- обработчики --------------------------------------------------------------------------------------------

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
    const page: ProjectPage = {
      items: found.slice(offset, offset + limit).map(toRow),
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
    return project ? HttpResponse.json(toCard(project, ok.writer)) : notFound();
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
        },
      },
      "contract.created",
      "contract",
      number,
      "Создан проект договора",
    );
    writeProject(next);
    return HttpResponse.json(toCard(next, ok.writer), { status: 201 });
  }),

  http.post("*/eds/projects/:ref/contract", async ({ request }) => {
    const ok = guard("full");
    if (ok.error) return ok.error;
    const p = findProject(refOf(request));
    if (!p?.contract) return notFound();
    const body = (await request.json()) as ProjectContractActionIn;
    if (body.action === "reject" && !body.reason?.trim()) {
      return failure(422, "VALIDATION_FAILED", "Проверьте заполнение полей.", "bff", {
        fields: ["reason"],
      });
    }
    const rule = TRANSITIONS[body.action];
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
    );
    writeProject(next);
    return HttpResponse.json(toCard(next, ok.writer));
  }),

  http.post("*/eds/projects/:ref/contract/scan", async ({ request }) => {
    const ok = guard("full");
    if (ok.error) return ok.error;
    const p = findProject(refOf(request));
    if (!p?.contract) return notFound();
    if (stateOf(p) !== "issued_at_operator") {
      return conflict("contract_transition_not_allowed", "Договор сейчас в другом статусе.");
    }
    const verdict = await scanVerdict(request.clone());
    if (verdict !== "ok") return scanFailure(verdict);
    const c = p.contract;
    const moment = now();
    // Подписан: ERP закрывает сделку как выигранную и создаёт черновик счёта на предоплату (D2-4 его выставит).
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
        contract: { ...c, status: "signed", signed_at: moment, has_scan: true },
      },
      "contract.scan_attached",
      "contract",
      c.number,
      "Прикреплён скан подписанного договора",
    );
    writeProject(next);
    return HttpResponse.json(toCard(next, ok.writer));
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
      return HttpResponse.json(toCard(next, ok.writer));
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
      return HttpResponse.json(toCard(next, ok.writer));
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
    return HttpResponse.json(toCard(next, ok.writer));
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
    return HttpResponse.json(toCard(next, ok.writer));
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
