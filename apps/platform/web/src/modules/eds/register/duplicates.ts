import { useEffect, useState } from "react";

import { ApiError } from "../../../shared/api/errors";
import type { LetterDuplicate, LetterDuplicateCheckIn } from "../../../shared/api/generated/model";
import { useCheckLetterDuplicates } from "../../../shared/api/generated/platform-bff";
import type { RegisterValues } from "./registerModel";

/** Поля формы для фоновой проверки (EDS-DUP); пустые не уходят. */
export function duplicateProbe(values: RegisterValues): LetterDuplicateCheckIn {
  const text = (value: string) => value.trim() || null;
  const inn = values.senderInn.trim();
  return {
    sender_name: text(values.senderName),
    sender_inn: /^\d{9,14}$/.test(inn) ? inn : null,
    sender_ref_number: text(values.refNumber),
    sender_ref_date: values.refDate || null,
    subject: text(values.subject),
    received_at: values.receivedAt || null,
    file_ids: [
      ...new Set(values.attachments.flatMap((a) => (a.status === "done" && a.id ? [a.id] : []))),
    ],
  };
}

/** Есть ли что проверять: корреспондент с номером или темой, или файл. */
function worthChecking(probe: LetterDuplicateCheckIn): boolean {
  const sender = Boolean(probe.sender_name ?? probe.sender_inn);
  return (
    (sender && Boolean(probe.sender_ref_number ?? probe.subject)) ||
    (probe.file_ids?.length ?? 0) > 0
  );
}

/** Задержка: запрос — когда сотрудник перестал печатать. */
function useSettled<T>(value: T, ms = 400): T {
  const [settled, setSettled] = useState(value);
  const key = JSON.stringify(value);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSettled(JSON.parse(key) as T);
    }, ms);
    return () => {
      window.clearTimeout(timer);
    };
  }, [key, ms]);
  return settled;
}

/** Фоновая проверка дублей формы регистрации (EDS-DUP): то же письмо и похожие. */
export function useDuplicateCheck(values: RegisterValues): LetterDuplicate[] {
  const probe = useSettled(duplicateProbe(values));
  const enabled = worthChecking(probe);
  const { mutate, data } = useCheckLetterDuplicates();
  const key = JSON.stringify(probe);
  useEffect(() => {
    // Ответ последнего запроса заменяет прежний; отказ проверки регистрацию не блокирует (сервер проверит сам).
    if (enabled) mutate({ data: JSON.parse(key) as LetterDuplicateCheckIn });
  }, [enabled, key, mutate]);
  return enabled ? (data?.items ?? []) : [];
}

/** Найденный ВХ из ответа 409 `duplicate_letter` (регистрация опередила фоновую проверку). */
export function duplicateFromError(error: unknown): LetterDuplicate | null {
  if (!(error instanceof ApiError) || error.details["reason"] !== "duplicate_letter") return null;
  const found = error.details["duplicate"];
  if (typeof found !== "object" || found === null) return null;
  const item = found as Partial<LetterDuplicate>;
  return typeof item.number === "string" && typeof item.path === "string"
    ? (item as LetterDuplicate)
    : null;
}

export interface ForceState {
  on: boolean;
  reason: string;
}
