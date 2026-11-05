import type {
  SigningAuthority,
  SigningAuthorityDetail,
  SigningAuthorityIn,
  SigningAuthorityPatch,
  SigningBasis,
} from "../../../shared/api/generated/model";
import { HOME_CURRENCY } from "../../../shared/lib/money";

/** Основания по порядку в форме: устав, приказ, доверенность (ADR-0024 п. 1). */
export const BASES: readonly SigningBasis[] = ["charter", "order", "power_of_attorney"];

/** Валюты лимита; другая валюта в полномочии — отдельный выбор администратора, пересчёта по курсу в подборе нет. */
export const CURRENCIES: readonly string[] = [HOME_CURRENCY, "USD", "EUR", "RUB"];

/** Доверенность — не больше трёх лет со дня выдачи (ГК РУз, ст. 139); 29 февраля в невисокосном году — 28 февраля. */
export function powerDeadline(issued: string): string {
  const [y = 0, m = 1, d = 1] = issued.split("-").map(Number);
  const moved = new Date(Date.UTC(y + 3, m - 1, d));
  if (moved.getUTCMonth() !== m - 1) moved.setUTCDate(0);
  return moved.toISOString().slice(0, 10);
}

export interface FormValues {
  holderId: string | undefined;
  kinds: string[];
  basis: SigningBasis;
  basisNumber: string;
  basisDate: string;
  validFrom: string;
  validTo: string;
  limitAmount: number | null;
  limitCurrency: string;
  vakolatUrl: string;
  note: string;
}

export function initialValues(
  today: string,
  authority: SigningAuthority | SigningAuthorityDetail | null,
  preset?: Partial<FormValues>,
): FormValues {
  if (authority) {
    return {
      holderId: authority.holder.id,
      kinds: authority.kinds,
      basis: authority.basis,
      basisNumber: authority.basis_number ?? "",
      basisDate: authority.basis_date ?? "",
      validFrom: authority.valid_from,
      validTo: authority.valid_to ?? "",
      limitAmount: authority.limit ? Number(authority.limit.amount) : null,
      limitCurrency: authority.limit?.currency ?? HOME_CURRENCY,
      vakolatUrl: authority.vakolat_url ?? "",
      note: authority.note ?? "",
    };
  }
  return {
    holderId: undefined,
    kinds: [],
    basis: "power_of_attorney",
    basisNumber: "",
    basisDate: "",
    validFrom: today,
    validTo: "",
    limitAmount: null,
    limitCurrency: HOME_CURRENCY,
    vakolatUrl: "",
    note: "",
    ...preset,
  };
}

function limitOf(values: FormValues): { amount: string; currency: string } | null {
  return values.limitAmount && values.limitAmount > 0
    ? { amount: values.limitAmount.toFixed(2), currency: values.limitCurrency }
    : null;
}

const orNull = (value: string): string | null => (value.trim() === "" ? null : value.trim());

type Terms = Omit<SigningAuthorityIn, "holder_id">;

/** Номер и дата нужны приказу и доверенности; у устава их нет, срок у доверенности обязателен (проверяет и EDS). */
function termsOf(values: FormValues): Terms {
  const numbered = values.basis !== "charter";
  return {
    kinds: values.kinds,
    limit: limitOf(values),
    basis: values.basis,
    basis_number: numbered ? orNull(values.basisNumber) : null,
    basis_date: numbered ? orNull(values.basisDate) : null,
    valid_from: values.validFrom,
    valid_to: orNull(values.validTo),
    vakolat_url: values.basis === "power_of_attorney" ? orNull(values.vakolatUrl) : null,
    note: orNull(values.note),
  };
}

export function toNewBody(values: FormValues): SigningAuthorityIn {
  return { holder_id: values.holderId ?? "", ...termsOf(values) };
}

/** Изменение шлёт все условия: EDS сама находит, что изменилось, и пишет «было / стало» в журнал. */
export function toPatchBody(values: FormValues): SigningAuthorityPatch {
  return termsOf(values);
}
