import type {
  AttentionItem,
  BrandProfile,
  FxRateOverview,
  IntegrationCardKey,
  IntegrationStatus,
  ServiceOwner,
  SetupStep,
  SigningAuthority,
} from "../../../shared/api/generated/model";
import { mergeSameCause } from "../integrations/attention";

/**
 * «Состояние» (ЕВ-2а, отчёт 2026-11-22 §8.3): что требует внимания, из каких фактов. Чистые функции без сети и React:
 * каждая строка выводится из факта (поле ответа сервера), а не из флага «настройка просмотрена» — тест правит факт и ждёт,
 * что строка появится или исчезнет.
 */

/** Окно напоминания об истекающем полномочии подписи, дней (`expiring` в EDS: за 14 дней до срока). */
export const SIGNING_WARN_DAYS = 14;

/** Кто исправляет: слова словаря `modules:admin.state.owner.*` */
export type StateOwner = ServiceOwner | "director" | "accountant";

export type AttentionKind = "service" | "signing" | "signingExpired" | "fx" | "blank" | "tickets";

export interface AttentionRow {
  id: string;
  kind: AttentionKind;
  /** `fail` — сбой, красным и первым; `warn` — внимание */
  severity: "fail" | "warn";
  owner: StateOwner;
  /** Страница, где это чинится; `null` — зрителю она закрыта, кнопки нет, остаётся «исправляет …» */
  to: string | null;
  /** Раздел реестра Настроек (`modules:admin.sections.<key>`) или `null`, если страница вне Настроек */
  page: string | null;
  /** Параметры текста строки (имя держателя, дни, число) */
  params: Record<string, string | number>;
  /** Для `service` — строка CRM «что случилось и что сделать» */
  item?: AttentionItem;
}

/** Страницы, куда ведёт «Открыть» сервисной строки: свои страницы каналов, остальное — «Сервисы» с окном карточки. */
const OWN_PAGE: Partial<Record<IntegrationCardKey, { to: string; page: string }>> = {
  telegram: { to: "/admin/telegram", page: "telegram" },
  mail: { to: "/admin/mail", page: "mail" },
  spend: { to: "/admin/ai-spend", page: "spend" },
};

export function cardTarget(card: IntegrationCardKey): { to: string; page: string } {
  return (
    OWN_PAGE[card] ?? { to: `/admin/integrations?card=${card}&panel=open`, page: "integrations" }
  );
}

const OWNERS: readonly ServiceOwner[] = ["admin", "owner", "hosting", "provider"];

/** Сбои и предупреждения сервисов из обзора «Сервисов»; «ещё не подключено» — не сбой, оно в готовности. */
export function serviceRows(
  attention: readonly AttentionItem[],
  canOpen: (page: string) => boolean = () => true,
): AttentionRow[] {
  return mergeSameCause(attention.filter((item) => item.severity !== "setup")).map((item) => {
    const target = cardTarget(item.card);
    const owner = item.group?.owner;
    return {
      id: `service:${item.id}`,
      kind: "service",
      severity: item.severity === "fail" ? "fail" : "warn",
      owner: owner && OWNERS.includes(owner) ? owner : "admin",
      to: canOpen(target.page) ? target.to : null,
      page: target.page,
      params: {},
      item,
    };
  });
}

/** Полномочие подписи, которое действует: по нему подписывают сейчас. */
const covers = (a: SigningAuthority) =>
  a.holder_active && (a.status === "active" || a.status === "expiring");

/**
 * Полномочия подписи, из-за которых документы могут остаться без подписанта (факт — реестр полномочий):
 * срок кончается в ближайшие 14 дней, либо срок уже вышел, а действующего преемника на те же виды подписи нет.
 * Истёкшее без преемника не пропадает из списка в день окончания срока — проблема только наступила.
 */
export function signingRows(authorities: readonly SigningAuthority[]): AttentionRow[] {
  const covered = new Set(authorities.filter(covers).flatMap((a) => a.kinds));
  const rows: AttentionRow[] = [];
  for (const a of authorities) {
    const params = {
      name: a.holder.name,
      days: a.expires_in_days ?? 0,
      basis: a.basis_number ?? "",
      until: a.valid_to ?? "",
    };
    const common = { owner: "admin" as const, to: "/admin/signing", page: "signing" };
    if (
      a.status === "expiring" &&
      a.holder_active &&
      a.expires_in_days !== null &&
      a.expires_in_days <= SIGNING_WARN_DAYS
    ) {
      rows.push({
        id: `signing:${a.id}`,
        kind: "signing",
        severity: "warn",
        ...common,
        params,
      });
    } else if (
      a.status === "expired" &&
      a.holder_active &&
      (a.kinds).some((kind) => !covered.has(kind))
    ) {
      rows.push({
        id: `signing:${a.id}`,
        kind: "signingExpired",
        severity: "fail",
        ...common,
        params,
      });
    }
  }
  return rows;
}

/** Свежего курса нет: ERP не получила курс за допустимый срок, расчёты в долларах недоступны. */
export function fxRows(fx: FxRateOverview | undefined): AttentionRow[] {
  if (!fx || fx.current !== null) return [];
  return [
    {
      id: "fx:stale",
      kind: "fx",
      severity: "warn",
      owner: "accountant",
      to: "/admin/taxes",
      page: "taxes",
      params: { currency: fx.currency, days: fx.max_age_days },
    },
  ];
}

/** Бланк не задан, пока в профиле бланка нет логотипа: письма на бланке не соберутся. */
export function blankRows(brand: BrandProfile | undefined): AttentionRow[] {
  if (!brand || brand.logo_url !== null) return [];
  return [
    {
      id: "blank:none",
      kind: "blank",
      severity: "warn",
      owner: "director",
      to: "/admin/company?part=brand",
      page: "company",
      params: {},
    },
  ];
}

/** Обращения сотрудников ждут ответа администратора — они в «Моих задачах», здесь только указатель. */
export function ticketRows(count: number): AttentionRow[] {
  if (count <= 0) return [];
  return [
    {
      id: "tickets:new",
      kind: "tickets",
      severity: "warn",
      owner: "admin",
      to: "/dashboard/queue",
      page: null,
      params: { count },
    },
  ];
}

/** Сбои — первыми, затем внимание; внутри — в порядке источников. */
export function ordered(rows: readonly AttentionRow[]): AttentionRow[] {
  const rank = (row: AttentionRow) => (row.severity === "fail" ? 0 : 1);
  return rows
    .map((row, index) => ({ row, index }))
    .sort((a, b) => rank(a.row) - rank(b.row) || a.index - b.index)
    .map(({ row }) => row);
}

/**
 * Состояние строки готовности. «Заполнено» и «работает» — разные факты: шаг сделан (`done`), а проверка карточки службы
 * показывает, что она отвечает (`ok`). Нет проверки (`card === undefined`) — остаётся «заполнено».
 */
export type ReadinessState = "works" | "filled" | "broken" | "todo" | "unknown";

export function readinessState(
  step: SetupStep["state"],
  card: IntegrationStatus | undefined,
): ReadinessState {
  if (step === "todo") return "todo";
  if (step === "unknown") return "unknown";
  if (card === undefined) return "filled";
  if (card === "ok") return "works";
  if (card === "fail" || card === "warn") return "broken";
  return "filled";
}

/** Очередь обмена между системами: сколько событий ждёт доставки и сколько не доставлено (по всем доменам). */
export function busLine(domains: readonly { outbox_pending: number; dlq_size: number }[]): {
  queued: number;
  dead: number;
} {
  return {
    queued: domains.reduce((sum, d) => sum + d.outbox_pending, 0),
    dead: domains.reduce((sum, d) => sum + d.dlq_size, 0),
  };
}
