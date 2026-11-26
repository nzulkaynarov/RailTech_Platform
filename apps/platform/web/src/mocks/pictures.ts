import { HttpResponse, type JsonBodyType, http } from "msw";

import { failure } from "./adminUsers";
import { parseUploadedFile } from "./edsDocuments";
import { buildMe, readSession } from "./mockSession";

/**
 * Логотип контрагента и фото его контакта на моках (ЕД-5, СУЩ-3): ERP хранит файл и отдаёт версию, BFF строит адрес с `?v=`.
 * Здесь хранится только версия; картинка — квадрат или круг цветом по номеру (как настоящий файл по тому же адресу).
 * Ключ логотипа — id компании ERP, ключ фото — id контакта.
 */
const logos = new Map<string, string>();
const photos = new Map<string, string>();
let counter = 0;

const TYPES = ["image/png", "image/jpeg", "image/webp"];

export function logoUrlOf(companyId: string): string | null {
  const version = logos.get(companyId);
  return version ? `/api/v1/people/counterparties/${companyId}/logo?v=${version}` : null;
}

export function photoUrlOf(contactId: string): string | null {
  const version = photos.get(contactId);
  return version ? `/api/v1/people/contacts/${contactId}/photo?v=${version}` : null;
}

/**
 * Компания клиента строки реестра (проект, счёт, письмо): id ERP и адрес логотипа, как их отдаёт BFF (ЕД-3). Логотип — у
 * двух компаний из трёх (по названию), остальные остаются с буквами: строка показывает обе картинки рядом.
 */
export function clientRefOf(name: string | null | undefined): {
  client_id: number | null;
  client_logo_url: string | null;
} {
  if (!name) return { client_id: null, client_logo_url: null };
  let hash = 0;
  for (const ch of name) hash = (hash * 31 + ch.charCodeAt(0)) % 100000;
  const id = 9000 + (hash % 900);
  if (hash % 3 === 0) return { client_id: id, client_logo_url: null };
  logos.set(String(id), "d1");
  return { client_id: id, client_logo_url: logoUrlOf(String(id)) };
}

/** Сброс между тестами и сценариями. */
export function resetPictures(): void {
  logos.clear();
  photos.clear();
  counter = 0;
}

function level(resource: "crm.clients" | "erp.stock"): string | undefined {
  const session = readSession();
  return session ? buildMe(session)?.resources[resource] : undefined;
}

/** Как в BFF: смотрит тот, кто видит карточку; правит тот, у кого полный `crm.clients` или `erp.stock`. */
function guard(write: boolean) {
  if (!readSession()) return failure(401, "SESSION_EXPIRED", "Сессия истекла");
  const allowed = write
    ? level("crm.clients") === "full" || level("erp.stock") === "full"
    : level("crm.clients") || level("erp.stock");
  return allowed
    ? null
    : failure(403, "FORBIDDEN", "Раздел или действие не положены вашей роли.", "bff");
}

function image(id: string, round: boolean) {
  const hue = (Number(id.replace(/\D/g, "")) * 47) % 360;
  const shape = round ? '<circle cx="48" cy="48" r="48"' : '<rect width="96" height="96" rx="8"';
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96">${shape} fill="hsl(${String(hue)} 55% 45%)"/><circle cx="48" cy="38" r="14" fill="#fff" opacity=".85"/><rect x="22" y="58" width="52" height="24" rx="12" fill="#fff" opacity=".85"/></svg>`;
  return new HttpResponse(svg, {
    headers: { "Content-Type": "image/svg+xml", "Cache-Control": "private, max-age=86400" },
  });
}

async function acceptedFile(request: Request): Promise<Response | null> {
  const file = await parseUploadedFile(request);
  if (!file || !TYPES.includes(file.type)) {
    return failure(422, "VALIDATION_FAILED", "Проверьте заполнение полей.", "erp", {
      fields: ["file"],
      reason: "file_type_not_allowed",
    });
  }
  return null;
}

export function pictureHandlers(cardOf: (companyId: string) => JsonBodyType) {
  return [
    http.get("*/people/counterparties/:id/logo", ({ params }) => {
      const denied = guard(false);
      if (denied) return denied;
      const id = String(params["id"]);
      return logos.has(id) ? image(id, false) : failure(404, "NOT_FOUND", "Логотипа нет.", "erp");
    }),
    http.put("*/people/counterparties/:id/logo", async ({ params, request }) => {
      const denied = guard(true);
      if (denied) return denied;
      const id = String(params["id"]);
      const card = cardOf(id);
      if (!card) return failure(404, "NOT_FOUND", "Контрагент не найден.", "erp");
      const refused = await acceptedFile(request);
      if (refused) return refused;
      counter += 1;
      logos.set(id, `v${String(counter)}`);
      return HttpResponse.json(cardOf(id));
    }),
    http.delete("*/people/counterparties/:id/logo", ({ params }) => {
      const denied = guard(true);
      if (denied) return denied;
      const id = String(params["id"]);
      logos.delete(id);
      const card = cardOf(id);
      return card
        ? HttpResponse.json(card)
        : failure(404, "NOT_FOUND", "Контрагент не найден.", "erp");
    }),
    http.get("*/people/contacts/:id/photo", ({ params }) => {
      const denied = guard(false);
      if (denied) return denied;
      const id = String(params["id"]);
      return photos.has(id) ? image(id, true) : failure(404, "NOT_FOUND", "Фото нет.", "erp");
    }),
    http.put("*/people/contacts/:id/photo", async ({ params, request }) => {
      const denied = guard(true);
      if (denied) return denied;
      const id = String(params["id"]);
      const refused = await acceptedFile(request);
      if (refused) return refused;
      counter += 1;
      photos.set(id, `v${String(counter)}`);
      return HttpResponse.json({ id, photo_url: photoUrlOf(id) });
    }),
    http.delete("*/people/contacts/:id/photo", ({ params }) => {
      const denied = guard(true);
      if (denied) return denied;
      const id = String(params["id"]);
      photos.delete(id);
      return HttpResponse.json({ id, photo_url: null });
    }),
  ];
}
