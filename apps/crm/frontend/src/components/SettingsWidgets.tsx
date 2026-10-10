import { Checkbox, DatePicker, Select, TimePicker } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import type { ReactElement } from "react";

import { useUsers } from "../api/queries";
import { pickerToTime, timeToPicker, type Widget } from "../domain/settingsLayout";
import { reasonLabel } from "../domain/labels";
import { t } from "../i18n/ru";
import { DATE_FORMAT } from "../lib/time";

/**
 * Типизированные поля настроек (дизайн-аудит 2026-10-11): время, дни недели, праздники,
 * часовой пояс, сотрудники по имени, причины передачи. Значения — в формате схемы API.
 */
type Field<T> = {
  value?: T | undefined;
  onChange?: ((value: T) => void) | undefined;
  id?: string | undefined;
};

/** `id` от Form.Item (связь с подписью) — только если он есть (exactOptionalPropertyTypes). */
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

/** 0 = понедельник … 6 = воскресенье (как `weekday()` в Python на бэке). */
function WeekdaysField({ value, onChange }: Field<number[]>) {
  return (
    <Checkbox.Group
      value={(value ?? []).map(Number)}
      options={t.settings.weekdays.map((label, day) => ({ value: day, label }))}
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
      format={DATE_FORMAT}
      className="settings-dates"
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
  const users = useUsers();
  const ids = (value ?? []).map(Number);
  const known = new Set((users.data ?? []).map((u) => u.id));
  const options = [
    ...(users.data ?? []).map((u) => ({
      value: u.id,
      label: u.is_active
        ? `${u.full_name} · ${u.email}`
        : `${u.full_name} · ${u.email} (${t.settings.inactiveUser})`,
    })),
    ...ids.filter((v) => !known.has(v)).map((v) => ({ value: v, label: `#${String(v)}` })),
  ];
  return (
    <Select
      {...idProp(id)}
      mode="multiple"
      showSearch
      optionFilterProp="label"
      loading={users.isLoading}
      placeholder={t.settings.usersPlaceholder}
      value={ids}
      onChange={(next: number[]) => {
        onChange?.(next);
      }}
      options={options}
    />
  );
}

function TriggersField({ value, onChange, id }: Field<string[]>) {
  const codes = [...new Set([...Object.keys(t.reasons), ...(value ?? [])])];
  return (
    <Select
      {...idProp(id)}
      mode="multiple"
      optionFilterProp="label"
      value={value ?? []}
      onChange={(next: string[]) => {
        onChange?.(next);
      }}
      options={codes.map((code) => ({ value: code, label: reasonLabel(code) }))}
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

/** Поле для `Form.Item`: antd передаёт `value`/`onChange`/`id` — пробрасываем виджету. */
export function SettingsWidget({ widget, ...field }: { widget: Widget } & Field<unknown>) {
  const Component = WIDGETS[widget] as (props: Field<unknown>) => ReactElement;
  return <Component {...field} />;
}
