import { HttpResponse, http } from "msw";

import type {
  Colleague,
  DeputyUpdate,
  ForgotPasswordIn,
  Profile,
  ProfileUpdate,
  ResetPasswordIn,
} from "../shared/api/generated/model";
import { readEmployees, writeEmployees } from "./fixtures/employees";
import { findUserById } from "./fixtures/users";
import { buildMe, readSession, sessionRoles, updateSession } from "./mockSession";
import {
  TELEGRAM_CONFIRM_KEY,
  avatarUrlOf,
  coveringFor,
  nameOf,
  patchProfile,
  readProfile,
  todayIso,
} from "./profileStore";

/** Ссылка сброса, которую «приносит» демо-письмо; другие значения дают «ссылка недействительна». */
export const DEMO_RESET_TOKEN = "demo-reset-token-0123456789abcdef";
const MAX_AVATAR = 1024 * 1024;
const AVATAR_TYPES = ["image/png", "image/jpeg", "image/webp"];
const PHONE = /^\+?[\d\s().-]+$/;

function failure(
  status: number,
  code: string,
  message: string,
  details?: Record<string, unknown>,
  source: "bff" | "crm" = "bff",
) {
  return HttpResponse.json({ code, message, source, ...(details ? { details } : {}) }, { status });
}

const expired = () => failure(401, "SESSION_EXPIRED", "Сессия истекла");

function currentUserId(): string | null {
  const session = readSession();
  return session ? (sessionRoles(session)?.user.id ?? null) : null;
}

function invalid(field: string, reason: string, message: string) {
  return failure(422, "VALIDATION_FAILED", message, { fields: [field], reason }, "crm");
}

function toProfile(userId: string): Profile {
  const user = findUserById(userId);
  const stored = readProfile(userId);
  const employee = readEmployees().find((e) => e.id === userId);
  const session = readSession();
  const avatar = avatarUrlOf(userId);
  const deputy = stored.deputy;
  const colleague = deputy ? findUserById(deputy.id) : undefined;
  return {
    name: nameOf(userId),
    email: user?.email ?? "",
    ...(user?.position ? { position: user.position } : {}),
    ...(stored.phone ? { phone: stored.phone } : {}),
    language: session?.language ?? user?.language ?? "ru",
    timezone: stored.timezone,
    ...(stored.signature ? { email_signature: stored.signature } : {}),
    ...(avatar ? { avatar_url: avatar } : {}),
    telegram: {
      linked: employee?.telegram_linked ?? false,
      ...(employee?.telegram_linked && stored.telegramUsername
        ? { username: stored.telegramUsername }
        : {}),
    },
    ...(deputy && colleague
      ? {
          deputy: {
            user_id: deputy.id,
            name: nameOf(colleague.id),
            date_from: deputy.date_from,
            date_to: deputy.date_to,
          },
        }
      : {}),
    covering: coveringFor(userId),
  };
}

/** Эмуляция бота: тест положил ник в `TELEGRAM_CONFIRM_KEY` — привязка подтверждена, ссылка погашена. */
function confirmTelegramIfAsked(userId: string): void {
  let nick: string | null;
  try {
    nick = window.localStorage.getItem(`${TELEGRAM_CONFIRM_KEY}-${userId}`);
  } catch {
    return;
  }
  const stored = readProfile(userId);
  if (nick === null || !stored.pendingLink) return;
  window.localStorage.removeItem(`${TELEGRAM_CONFIRM_KEY}-${userId}`);
  writeEmployees(
    readEmployees().map((e) => (e.id === userId ? { ...e, telegram_linked: true } : e)),
  );
  patchProfile(userId, { pendingLink: false, telegramUsername: nick });
}

function validPhone(raw: string): boolean {
  if (raw.trim() === "") return true;
  const digits = raw.replace(/\D/g, "").length;
  return PHONE.test(raw.trim()) && digits >= 7 && digits <= 15;
}

function validZone(zone: string): boolean {
  try {
    new Intl.DateTimeFormat("en", { timeZone: zone });
    return true;
  } catch {
    return false;
  }
}

function dataUrlToResponse(dataUrl: string): Response | null {
  const match = /^data:([^;]+);base64,(.*)$/.exec(dataUrl);
  const mime = match?.[1];
  const body = match?.[2];
  if (!mime || body === undefined) return null;
  const binary = atob(body);
  const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
  return new Response(bytes, {
    status: 200,
    headers: { "content-type": mime, "x-content-type-options": "nosniff" },
  });
}

function indexOfBytes(haystack: Uint8Array, needle: Uint8Array, from = 0): number {
  outer: for (let i = from; i <= haystack.length - needle.length; i += 1) {
    for (let k = 0; k < needle.length; k += 1) {
      if (haystack[i + k] !== needle[k]) continue outer;
    }
    return i;
  }
  return -1;
}

interface Upload {
  type: string;
  bytes: Uint8Array;
}

/**
 * Часть `avatar` multipart без `request.formData()`: в jsdom (vitest) разбор форм в Node не знает чужой `File`, а мок
 * работает и там, и в браузере. Картинка — двоичная, поэтому границы ищем по байтам.
 */
async function parseAvatar(request: Request): Promise<Upload | null> {
  const boundary = /boundary=([^;]+)/.exec(request.headers.get("content-type") ?? "")?.[1];
  if (!boundary) return null;
  const body = new Uint8Array(await request.arrayBuffer());
  const encoder = new TextEncoder();
  const marker = encoder.encode(`--${boundary}`);
  let start = indexOfBytes(body, marker);
  while (start >= 0) {
    const headEnd = indexOfBytes(body, encoder.encode("\r\n\r\n"), start);
    const next = indexOfBytes(body, marker, start + marker.length);
    if (headEnd < 0 || next < 0) return null;
    const head = new TextDecoder().decode(body.slice(start, headEnd));
    if (/name="avatar"/.test(head)) {
      const type = /content-type:\s*([^\r\n]+)/i.exec(head)?.[1]?.trim() ?? "";
      return { type, bytes: body.slice(headEnd + 4, next - 2) };
    }
    start = next;
  }
  return null;
}

function toDataUrl(upload: Upload): string {
  let binary = "";
  for (const byte of upload.bytes) binary += String.fromCharCode(byte);
  return `data:${upload.type};base64,${btoa(binary)}`;
}

/**
 * Моки профиля `/me`, фото, Telegram, замещения и «Забыли пароль?» (W15-H6). Правила значений повторяют CRM: телефон
 * 7–15 цифр, известный пояс, фото PNG/JPEG/WebP до 1 МБ, замещение — не себя, период не в прошлом и не длиннее года.
 */
export const profileHandlers = [
  http.get("*/me/profile", () => {
    const userId = currentUserId();
    if (!userId) return expired();
    confirmTelegramIfAsked(userId);
    return HttpResponse.json(toProfile(userId));
  }),

  http.patch("*/me/profile", async ({ request }) => {
    const userId = currentUserId();
    if (!userId) return expired();
    const body = (await request.json()) as ProfileUpdate;
    if (body.phone !== undefined && !validPhone(body.phone)) {
      return invalid("phone", "phone_invalid", "Телефон: от 7 до 15 цифр, можно с «+».");
    }
    if (body.timezone !== undefined && !validZone(body.timezone)) {
      return invalid("timezone", "timezone_unknown", "Такого часового пояса нет.");
    }
    if (body.email_signature !== undefined && body.email_signature.length > 1000) {
      return invalid("email_signature", "signature_invalid", "Подпись не длиннее 1000 символов.");
    }
    patchProfile(userId, {
      ...(body.name !== undefined ? { name: body.name.trim() } : {}),
      ...(body.phone !== undefined
        ? { phone: body.phone.trim() === "" ? undefined : `+${body.phone.replace(/\D/g, "")}` }
        : {}),
      ...(body.timezone !== undefined ? { timezone: body.timezone } : {}),
      ...(body.email_signature !== undefined
        ? {
            signature: body.email_signature.trim() === "" ? undefined : body.email_signature.trim(),
          }
        : {}),
    });
    if (body.language) updateSession({ language: body.language });
    return HttpResponse.json(toProfile(userId));
  }),

  http.put("*/me/avatar", async ({ request }) => {
    const userId = currentUserId();
    if (!userId) return expired();
    const file = await parseAvatar(request);
    if (!file || file.bytes.length === 0) {
      return invalid("avatar", "avatar_empty", "Файл пустой.");
    }
    if (!AVATAR_TYPES.includes(file.type)) {
      return invalid("avatar", "avatar_unsupported_type", "Нужна картинка PNG, JPEG или WebP.");
    }
    if (file.bytes.length > MAX_AVATAR) {
      return invalid("avatar", "avatar_too_large", "Фото больше 1 МБ.");
    }
    patchProfile(userId, {
      avatar: toDataUrl(file),
      avatarVersion: Math.floor(Date.now() / 1000),
    });
    const session = readSession();
    const me = session ? buildMe(session) : undefined;
    return me ? HttpResponse.json(me) : expired();
  }),

  http.delete("*/me/avatar", () => {
    const userId = currentUserId();
    if (!userId) return expired();
    patchProfile(userId, { avatar: undefined, avatarVersion: undefined });
    const session = readSession();
    const me = session ? buildMe(session) : undefined;
    return me ? HttpResponse.json(me) : expired();
  }),

  http.get("*/staff/:id/avatar", ({ params }) => {
    if (!currentUserId()) return expired();
    const avatar = readProfile(String(params["id"])).avatar;
    const response = avatar ? dataUrlToResponse(avatar) : null;
    return response ?? failure(404, "NOT_FOUND", "Фото нет.");
  }),

  http.post("*/me/telegram-link", () => {
    const userId = currentUserId();
    if (!userId) return expired();
    patchProfile(userId, { pendingLink: true });
    return HttpResponse.json({
      url: "https://t.me/rt_demo_bot?start=staff_Zm9yLXRoZS1kZW1v",
      expires_at: new Date(Date.now() + 10 * 60 * 1000).toISOString(),
    });
  }),

  http.delete("*/me/telegram-link", () => {
    const userId = currentUserId();
    if (!userId) return expired();
    writeEmployees(
      readEmployees().map((e) => (e.id === userId ? { ...e, telegram_linked: false } : e)),
    );
    patchProfile(userId, { pendingLink: false, telegramUsername: undefined });
    return HttpResponse.json(toProfile(userId));
  }),

  http.get("*/me/deputy-candidates", () => {
    const userId = currentUserId();
    if (!userId) return expired();
    const items: Colleague[] = readEmployees()
      .filter((e) => e.id !== userId && e.status !== "disabled" && e.status !== "invited")
      .flatMap((e) => {
        const user = findUserById(e.id);
        return user && user.roles.some((r) => r === "MANAGER" || r === "DIRECTOR" || r === "ADMIN")
          ? [{ id: e.id, name: nameOf(e.id), position: user.position }]
          : [];
      });
    return HttpResponse.json(items);
  }),

  http.put("*/me/deputy", async ({ request }) => {
    const userId = currentUserId();
    if (!userId) return expired();
    const body = (await request.json()) as DeputyUpdate;
    const field = "deputy_id";
    if (body.deputy_id === userId) {
      return invalid(field, "deputy_is_self", "Заместителем нельзя назначить себя.");
    }
    if (body.date_to < body.date_from) {
      return invalid("date_to", "deputy_period_reversed", "Дата окончания раньше даты начала.");
    }
    if (body.date_to < todayIso()) {
      return invalid("date_to", "deputy_period_past", "Период уже закончился.");
    }
    const days = (Date.parse(body.date_to) - Date.parse(body.date_from)) / 86_400_000;
    if (days > 366) {
      return invalid("date_to", "deputy_period_too_long", "Период не может быть длиннее года.");
    }
    const colleague = readEmployees().find((e) => e.id === body.deputy_id);
    if (!colleague || colleague.status === "disabled") {
      return invalid(field, "deputy_not_colleague", "Этот сотрудник не может вести очередь.");
    }
    patchProfile(userId, {
      deputy: { id: body.deputy_id, date_from: body.date_from, date_to: body.date_to },
    });
    return HttpResponse.json(toProfile(userId));
  }),

  http.delete("*/me/deputy", () => {
    const userId = currentUserId();
    if (!userId) return expired();
    patchProfile(userId, { deputy: undefined });
    return HttpResponse.json(toProfile(userId));
  }),

  http.post("*/auth/forgot-password", async ({ request }) => {
    const body = (await request.json()) as ForgotPasswordIn;
    // Адрес limit@ показывает путь «слишком много запросов»; остальные — один и тот же ответ.
    if (body.identifier.toLowerCase().startsWith("limit@")) {
      return HttpResponse.json(
        { code: "TOO_MANY_REQUESTS", message: "Слишком много запросов.", source: "bff" },
        { status: 429, headers: { "Retry-After": "3600" } },
      );
    }
    return HttpResponse.json({ accepted: true }, { status: 202 });
  }),

  http.post("*/auth/reset-password", async ({ request }) => {
    const body = (await request.json()) as ResetPasswordIn;
    if (body.token !== DEMO_RESET_TOKEN) {
      return invalid("token", "reset_token_invalid", "Ссылка недействительна или устарела.");
    }
    if (body.new_password.length < 10 || !/\d/.test(body.new_password)) {
      return invalid("new_password", "weak_password", "Пароль слишком простой.");
    }
    return new HttpResponse(null, { status: 204 });
  }),
];
