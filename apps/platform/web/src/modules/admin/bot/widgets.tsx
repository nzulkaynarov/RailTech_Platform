import { Checkbox, DatePicker, Select, TimePicker } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import type { ReactElement } from "react";
import { useTranslation } from "react-i18next";

import { useListEmployees } from "../../../shared/api/generated/platform-bff";
import { pickerToTime, timeToPicker, type Widget } from "./sections";

/**
 * Типизированные поля настроек: время, дни недели, праздники, часовой пояс, сотрудники по имени, причины передачи.
 * Значения — в формате схемы API (`HH:mm:00`, 0 = понедельник, `YYYY-MM-DD`, id сотрудника CRM).
 */
interface Field<T> {
  value?: T | undefined;
  onChange?: ((value: T) => void) | undefined;
  id?: string | undefined;
  /** Подпись поля для группы флажков (у выпадающих списков подпись — `label for`) */
  label?: string | undefined;
}

/** `id` от `Form.Item` (связь с подписью) — только если он есть (exactOptionalPropertyTypes). */
const idProp = (id: string | undefined) => (id ? { id } : {});

function TimeField({ value, onChange, id }: Field<string | null>) {
  const hhmm = timeToPicker(value);
  return (
    <TimePicker
      {...idProp(id)}
      format="HH:mm"
      minuteStep={5}
      needConfirm={false}
      allowClear={false}
      value={hhmm ? dayjs(`1970-01-01T${hhmm}:00`) : null}
      onChange={(v: Dayjs | null) => {
        if (v) onChange?.(pickerToTime(v.format("HH:mm")));
      }}
    />
  );
}

const WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;

/** 0 = понедельник … 6 = воскресенье (как `weekday()` в Python на стороне CRM). */
function WeekdaysField({ value, onChange, label }: Field<number[]>) {
  const { t } = useTranslation("bot");
  return (
    <Checkbox.Group
      {...(label ? { role: "group", "aria-label": label } : {})}
      value={(value ?? []).map(Number)}
      options={WEEKDAYS.map((key, day) => ({ value: day, label: t(`weekdays.${key}`) }))}
      onChange={(days) => {
        onChange?.([...days].sort((a, b) => a - b));
      }}
    />
  );
}

function DatesField({ value, onChange, id }: Field<string[]>) {
  return (
    <DatePicker
      {...idProp(id)}
      multiple
      format="DD.MM.YYYY"
      style={{ width: "100%" }}
      value={(value ?? []).map((d) => dayjs(d))}
      onChange={(dates: Dayjs[] | null) => {
        onChange?.((dates ?? []).map((d) => d.format("YYYY-MM-DD")).sort());
      }}
    />
  );
}

function timezones(current: string | undefined): string[] {
  const all = Intl.supportedValuesOf("timeZone");
  return current && !all.includes(current) ? [current, ...all] : all;
}

function TimezoneField({ value, onChange, id }: Field<string>) {
  return (
    <Select
      {...idProp(id)}
      showSearch
      value={value ?? null}
      onChange={(zone: string) => {
        onChange?.(zone);
      }}
      options={timezones(value).map((zone) => ({ value: zone, label: zone }))}
    />
  );
}

function UsersField({ value, onChange, id }: Field<number[]>) {
  const { t } = useTranslation("bot");
  const users = useListEmployees();
  const ids = (value ?? []).map(Number);
  // id сотрудника BFF — строка `crm_user_id`; в настройках CRM хранит числа.
  const options = [
    ...(users.data?.items ?? []).map((u) => ({
      value: Number(u.id),
      label: `${u.name} · ${u.email}${u.status === "disabled" ? ` (${t("widgets.inactiveUser")})` : ""}`,
    })),
  ];
  const known = new Set(options.map((o) => o.value));
  const unknown = ids
    .filter((v) => !known.has(v))
    .map((v) => ({ value: v, label: `#${String(v)}` }));
  return (
    <Select
      {...idProp(id)}
      mode="multiple"
      showSearch
      optionFilterProp="label"
      loading={users.isPending}
      placeholder={t("widgets.usersPlaceholder")}
      value={ids}
      onChange={(next: number[]) => {
        onChange?.(next);
      }}
      options={[...options, ...unknown]}
    />
  );
}

const TRIGGER_CODES = [
  "human_requested",
  "callback_requested",
  "price_or_contract_asked",
  "negative_sentiment",
  "complaint",
  "kb_gap_streak",
  "no_progress",
  "competitor_mentioned",
  "high_score",
  "qualifier_recommend",
  "document_not_found",
  "service_request",
  "attachment_received",
  "agent_unavailable",
  "delivery_failed",
] as const;

function TriggersField({ value, onChange, id }: Field<string[]>) {
  const { t } = useTranslation("kb");
  const codes = [...new Set([...TRIGGER_CODES, ...(value ?? [])])];
  return (
    <Select
      {...idProp(id)}
      mode="multiple"
      optionFilterProp="label"
      value={value ?? []}
      onChange={(next: string[]) => {
        onChange?.(next);
      }}
      options={codes.map((code) => ({
        value: code,
        label: t(`triggers.${code}`, { defaultValue: code }),
      }))}
    />
  );
}

const WIDGETS = {
  time: TimeField,
  weekdays: WeekdaysField,
  dates: DatesField,
  timezone: TimezoneField,
  users: UsersField,
  triggers: TriggersField,
} as const;

/** Поле для `Form.Item`: antd передаёт `value`, `onChange`, `id` — пробрасываем виджету. */
export function SettingsWidget({ widget, ...field }: { widget: Widget } & Field<unknown>) {
  const Component = WIDGETS[widget] as (props: Field<unknown>) => ReactElement;
  return <Component {...field} />;
}
