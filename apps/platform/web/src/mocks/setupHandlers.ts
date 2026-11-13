import { HttpResponse, http } from "msw";

import type {
  SetupAdminIn,
  SetupCabinet,
  SetupCabinetCheck,
  SetupCabinetCheckIn,
  SetupCabinetIn,
  SetupChecklist,
  SetupCompanyIn,
  SetupStepKey,
} from "../shared/api/generated/model";
import { failure, guard } from "./adminUsers";
import { companyBankReady } from "./fixtures/company";
import { ROLE_ID } from "./fixtures/roles";
import { readEmployees, writeEmployees } from "./fixtures/employees";
import { registerUser } from "./fixtures/users";
import { buildSession, startSession } from "./mockSession";
import { type SetupMock, readSetup, writeSetup } from "./setupState";
import { readKb } from "./fixtures/kb";

const STEPS: readonly SetupStepKey[] = ["erp", "bot", "mail", "models", "first_employee"];

/** Чистая установка без шага «ERP»: ERP не сопряжена, компания невозможна (BFF 0.15.0, `ERP_NOT_CONNECTED`). */
function cabinetOf(state: SetupMock): SetupCabinet {
  const env = state.cabinetEnv ?? null;
  if (state.cabinetUrl) return { url: state.cabinetUrl, source: "saved", env_url: env };
  return env
    ? { url: env, source: "env", env_url: env }
    : { url: null, source: "none", env_url: null };
}

function erpNotConnected(): boolean {
  const state = readSetup();
  return state.fresh && !state.done.erp;
}

function initialsOf(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part.charAt(0).toLocaleUpperCase())
    .join("");
}

/** Правила пароля CRM: не короче 10 символов, буквы и цифры, без имени из почты. */
function weakPassword(password: string, email: string): boolean {
  const local = email.split("@")[0]?.toLowerCase() ?? "";
  return (
    password.length < 10 ||
    !/\d/.test(password) ||
    !/\p{L}/u.test(password) ||
    (local !== "" && password.toLowerCase().includes(local))
  );
}

/** Моки `/setup/*` (W13-A4): те же отказы, что у BFF, состояние — в `setupState`. */
export const setupHandlers = [
  // Название — из той же настройки «Компания» (CRM `company.name`), что правит «Настройки · Компания» (задача «Н3»).
  http.get("*/setup/state", () => {
    const company = readKb().settings["company"] as { name?: string } | undefined;
    return HttpResponse.json({
      needs_admin: readSetup().needsAdmin,
      company_name: company?.name?.trim() || null,
    });
  }),

  http.post("*/setup/admin", async ({ request }) => {
    const body = (await request.json()) as SetupAdminIn;
    const state = readSetup();
    if (!state.needsAdmin) {
      return failure(409, "SETUP_DONE", "Администратор уже создан. Войдите в Платформу.", "crm");
    }
    const normalize = (value: string) => value.replace(/[^a-z0-9]/gi, "").toUpperCase();
    if (normalize(body.code) !== normalize(state.code)) {
      return failure(422, "SETUP_CODE_INVALID", "Код неверный.", "crm", { fields: ["code"] });
    }
    if (weakPassword(body.password, body.email)) {
      return failure(422, "VALIDATION_FAILED", "Проверьте заполнение полей.", "crm", {
        fields: ["password"],
        reason: "weak_password",
      });
    }
    const name = body.name.trim();
    const email = body.email.trim().toLowerCase();
    const user = {
      id: "u-first-admin",
      email,
      name,
      initials: initialsOf(name),
      position: "Администратор",
      roles: ["ADMIN" as const],
      language: "ru" as const,
    };
    registerUser(user);
    writeEmployees([
      ...readEmployees().filter((e) => e.id !== user.id),
      {
        id: user.id,
        name,
        initials: user.initials,
        email,
        position: user.position,
        role_ids: [ROLE_ID.ADMIN],
        access: { crm: true, erp: true },
        status: "active",
        telegram_linked: false,
        erp_sync: "ok",
      },
    ]);
    writeSetup({ ...state, needsAdmin: false });
    const session = buildSession(startSession(user));
    return session ? HttpResponse.json(session) : failure(500, "INTERNAL_ERROR", "Нет сессии");
  }),

  http.get("*/setup/checklist", () => {
    const denied = guard("full");
    if (denied) return denied;
    const state = readSetup();
    const steps = STEPS.map((key) => ({
      key,
      state: !state.fresh || state.done[key] ? ("done" as const) : ("todo" as const),
    }));
    const body: SetupChecklist = {
      steps,
      done: steps.filter((s) => s.state === "done").length,
      total: 5,
      company: erpNotConnected()
        ? null
        : {
            required: !state.companyCreated,
            can_setup: !state.companyCreated,
            // D26G-6: своей компании нет — предупреждать не о чем (как ERP `setup/status`)
            bank_details_ready: !state.companyCreated || companyBankReady(),
          },
      company_blocker: erpNotConnected() ? "erp_not_connected" : null,
    };
    return HttpResponse.json(body);
  }),

  // D17G-3: адрес кабинета клиента — из настроек, иначе «с сервера»; проверка: адрес с «unreachable» не открывается
  http.get("*/setup/cabinet", () => {
    const denied = guard("full");
    if (denied) return denied;
    return HttpResponse.json(cabinetOf(readSetup()));
  }),

  http.put("*/setup/cabinet", async ({ request }) => {
    const denied = guard("full");
    if (denied) return denied;
    const { url } = (await request.json()) as SetupCabinetIn;
    const typed = url.trim().replace(/\/+$/, "");
    if (typed !== "" && !/^https?:\/\/[^\s/]+/.test(typed)) {
      return failure(422, "VALIDATION_FAILED", "Проверьте заполнение полей.", "crm", {
        fields: ["url"],
      });
    }
    const state = { ...readSetup(), cabinetUrl: typed };
    writeSetup(state);
    return HttpResponse.json(cabinetOf(state));
  }),

  http.post("*/setup/cabinet/check", async ({ request }) => {
    const denied = guard("full");
    if (denied) return denied;
    const { url } = (await request.json()) as SetupCabinetCheckIn;
    const target = url?.trim() || cabinetOf(readSetup()).url;
    const body: SetupCabinetCheck = !target
      ? { result: "not_set", url: null, status_code: null }
      : target.includes("unreachable")
        ? { result: "unreachable", url: target, status_code: null }
        : { result: "ok", url: target, status_code: 200 };
    return HttpResponse.json(body);
  }),

  http.post("*/setup/company", async ({ request }) => {
    const denied = guard("full");
    if (denied) return denied;
    const body = (await request.json()) as SetupCompanyIn;
    const state = readSetup();
    if (erpNotConnected()) {
      return failure(
        409,
        "ERP_NOT_CONNECTED",
        "ERP не подключена. Сначала подключите ERP (Настройки · Подключения · ERP), затем создайте компанию.",
        "bff",
        { reason: "erp_not_connected", link: "/admin/integrations?card=erp&panel=open" },
      );
    }
    if (state.companyCreated) {
      return failure(409, "OWN_COMPANY_ALREADY_EXISTS", "Своя компания уже создана.", "erp");
    }
    // ИНН 000… — «занят» (проверка ошибки поля)
    if (body.inn && /^0+$/.test(body.inn)) {
      return failure(422, "VALIDATION_FAILED", "Проверьте заполнение полей.", "erp", {
        fields: ["inn"],
        messages: { inn: "Компания с таким ИНН уже есть." },
      });
    }
    writeSetup({ ...state, companyCreated: true });
    return HttpResponse.json({ id: 1, name: body.name.trim() }, { status: 201 });
  }),
];
