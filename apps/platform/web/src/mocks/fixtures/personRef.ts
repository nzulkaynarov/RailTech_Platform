import type { PersonRef } from "../../shared/api/generated/model";
import { allUsers } from "./users";

/** «Кто сделал» в моке (СУЩ-3): имя → ссылка на демо-сотрудника с тем же именем; не нашёлся — имя без id. */
export function staffRef(name: string): PersonRef;
export function staffRef(name: string | null): PersonRef | null;
export function staffRef(name: string | null): PersonRef | null {
  if (!name) return null;
  const user = allUsers().find((u) => u.name === name);
  return { id: user?.id ?? "", name, initials: user?.initials ?? initials(name) };
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join("");
}
