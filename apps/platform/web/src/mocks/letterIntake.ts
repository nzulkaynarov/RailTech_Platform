import { HttpResponse, http } from "msw";

import { allows } from "../app/rbac.generated";
import type {
  AiDecisionIn,
  DocflowSettings,
  DocflowSettingsPatch,
  LetterIntakeIn,
  LetterIntakeSuggestion,
} from "../shared/api/generated/model";
import { readEds } from "./fixtures/edsDocuments";
import { buildMe, readSession } from "./mockSession";

/**
 * Моки «Заполнить из файла» и настроек документооборота (EDS-REG). Модели нет: PDF «с текстом» отвечает вымышленным
 * требованием налоговой; скан или фото — только при включённом «Распознавать сканы». Решения пишутся в память — для
 * тестов (`intakeDecisions`). Настройки — `localStorage`, как остальные моки.
 */
const KEY = "rt-pf-mock-docflow-settings";
export const intakeDecisions: AiDecisionIn["decision"][] = [];
let memory: DocflowSettings | null = null;

export function readDocflowSettings(): DocflowSettings {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (raw) return JSON.parse(raw) as DocflowSettings;
  } catch {
    // Хранилище недоступно — состояние в памяти.
  }
  return memory ?? { recognize_scans: false, ai_available: true };
}

export function writeDocflowSettings(next: DocflowSettings): void {
  memory = next;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // Остаётся копия в памяти.
  }
}

export function resetLetterIntakeMock(): void {
  memory = null;
  intakeDecisions.length = 0;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // Нечего сбрасывать.
  }
}

function resources() {
  const session = readSession();
  const me = session ? buildMe({ ...session, activeRole: null }) : null;
  return me?.resources ?? null;
}

const fail = (status: number, code: string, message: string, details?: Record<string, unknown>) =>
  HttpResponse.json({ code, message, source: "eds", ...(details ? { details } : {}) }, { status });

/** Вымышленное письмо налоговой — ответ «помощника» на PDF с текстом. */
export const DEMO_SUGGESTION: Omit<LetterIntakeSuggestion, "suggestion_id" | "source"> = {
  fields: {
    sender_name: "ГНИ Демо-района",
    sender_inn: "301234567",
    sender_ref_number: "04-12/7788",
    sender_ref_date: "2026-10-30",
    subject: "Требование о пояснениях по НДС за III квартал",
    summary:
      "Просят пояснить расхождение в декларации по НДС и представить документы до 12 ноября.",
    kind: "tax_notice",
    document_due: "2026-11-12",
  },
  alias: "intake-model",
  prompt_version: "demo00000001",
};

export const letterIntakeHandlers = [
  http.post("*/eds/letter-intake", async ({ request }) => {
    const held = resources();
    if (!held) return fail(401, "SESSION_EXPIRED", "Сессия истекла");
    if (!allows(held, "eds.inbox.register", "full")) {
      return fail(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.");
    }
    const { file_id: fileId } = (await request.json()) as LetterIntakeIn;
    const file = readEds().files[fileId];
    if (!file) return fail(404, "NOT_FOUND", "Файл не найден.");
    const image = file.content_type.startsWith("image/") || /скан|scan/i.test(file.name);
    if (!file.content_type.includes("pdf") && !file.content_type.startsWith("image/")) {
      return fail(422, "VALIDATION_FAILED", "Заполнить можно из PDF или фото письма.", {
        fields: ["file_id"],
        reason: "unsupported_file",
      });
    }
    if (image && !readDocflowSettings().recognize_scans) {
      return fail(409, "CONFLICT", "Распознавание сканов выключено — заполните вручную.", {
        reason: "scan_recognition_disabled",
      });
    }
    const suggestion: LetterIntakeSuggestion = {
      ...DEMO_SUGGESTION,
      suggestion_id: crypto.randomUUID(),
      source: image ? "image" : "text",
    };
    return HttpResponse.json(suggestion);
  }),

  http.post("*/eds/ai-suggestions/:id/decision", async ({ request }) => {
    const held = resources();
    if (!held) return fail(401, "SESSION_EXPIRED", "Сессия истекла");
    intakeDecisions.push(((await request.json()) as AiDecisionIn).decision);
    return new HttpResponse(null, { status: 204 });
  }),

  http.get("*/eds/docflow-settings", () => {
    const held = resources();
    if (!held) return fail(401, "SESSION_EXPIRED", "Сессия истекла");
    if (!allows(held, "eds.inbox.register", "full") && !allows(held, "admin", "read")) {
      return fail(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.");
    }
    return HttpResponse.json(readDocflowSettings());
  }),

  http.patch("*/eds/docflow-settings", async ({ request }) => {
    const held = resources();
    if (!held) return fail(401, "SESSION_EXPIRED", "Сессия истекла");
    if (!allows(held, "admin", "full")) {
      return fail(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.");
    }
    const body = (await request.json()) as DocflowSettingsPatch;
    const next = { ...readDocflowSettings(), recognize_scans: body.recognize_scans };
    writeDocflowSettings(next);
    return HttpResponse.json(next);
  }),
];
