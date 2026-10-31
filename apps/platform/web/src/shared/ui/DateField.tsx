import { DatePicker } from "antd";
import enGB from "antd/es/date-picker/locale/en_GB";
import ruRU from "antd/es/date-picker/locale/ru_RU";
import uzUZ from "antd/es/date-picker/locale/uz_UZ";
import dayjs, { type Dayjs } from "dayjs";
import customParseFormat from "dayjs/plugin/customParseFormat";
import "dayjs/locale/en-gb";
import "dayjs/locale/ru";
import "dayjs/locale/uz-latn";
import { type CSSProperties, type ReactNode, useLayoutEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

dayjs.extend(customParseFormat);

type PickerLocale = typeof ruRU;
type PickerHandle = { nativeElement?: HTMLElement | null } | null;

const ISO = "YYYY-MM-DD";
const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Показ — `ДД.ММ.ГГГГ`; с клавиатуры дату можно набрать так же, цифрами подряд (`31102026`), с одной цифрой дня и месяца
 * (`1.11.2026`) или ключом `2026-10-31`. Первый формат — формат показа.
 */
const DATE_INPUT_FORMATS = ["DD.MM.YYYY", "DDMMYYYY", "D.M.YYYY", "YYYY-MM-DD"];

/**
 * Локаль календаря по языку интерфейса: названия месяцев и дней берёт dayjs, поэтому узбекский — латиница `uz-latn`
 * (у antd `uz_UZ` dayjs взял бы кириллицу `uz`), английский — британский (неделя с понедельника, как у ru и uz).
 */
const PICKER_LOCALES: Record<string, PickerLocale> = {
  ru: ruRU,
  uz: { ...uzUZ, lang: { ...uzUZ.lang, locale: "uz-latn" } },
  en: enGB,
};

function toDay(value: string | null | undefined): Dayjs | null {
  if (!value || !ISO_DAY.test(value)) return null;
  const day = dayjs(value, ISO, true);
  return day.isValid() ? day : null;
}

export interface DateFieldProps {
  id?: string | undefined;
  /** Дата ключом `YYYY-MM-DD`; пусто — `""`, `null` или `undefined`. */
  value?: string | null | undefined;
  /** Наружу — ключ `YYYY-MM-DD` или `""` после очистки: формы и API получают то же, что от системного поля. */
  onChange?: ((value: string) => void) | undefined;
  /** Не раньше этого дня (`YYYY-MM-DD`), например `companyToday()` из `shared/lib/dates`. */
  min?: string | undefined;
  /** Не позже этого дня (`YYYY-MM-DD`). */
  max?: string | undefined;
  allowClear?: boolean | undefined;
  disabled?: boolean | undefined;
  status?: "error" | "warning" | undefined;
  placeholder?: string | undefined;
  className?: string | undefined;
  style?: CSSProperties | undefined;
  onBlur?: (() => void) | undefined;
  "aria-label"?: string | undefined;
  "aria-describedby"?: string | undefined;
  "aria-invalid"?: boolean | "true" | "false" | undefined;
  "aria-required"?: boolean | undefined;
}

/**
 * Поле даты Платформы вместо системного `input type="date"` (он показывал `mm/dd/yyyy`): antd `DatePicker` с форматом
 * `ДД.ММ.ГГГГ`, календарём на языке интерфейса и вводом с клавиатуры. Значение — строка `YYYY-MM-DD`. Границы `min`/`max`
 * отключают дни в календаре; дату вне них, набранную с клавиатуры, поле не стирает молча, а отдаёт форме — как системное
 * поле с `min`/`max`: форма проверяет её и пишет ошибку словами («Срок не может быть в прошлом»). Подпись — `label for={id}`
 * или `aria-label`.
 */
export function DateField({
  id,
  value,
  onChange,
  min,
  max,
  allowClear = true,
  disabled,
  status,
  placeholder,
  className,
  style,
  onBlur,
  "aria-invalid": ariaInvalid,
  ...aria
}: DateFieldProps) {
  const { t, i18n } = useTranslation("ui");
  const ref = useRef<PickerHandle>(null);
  const marked = useRef(false);
  const invalid = ariaInvalid === true || ariaInvalid === "true";
  const locale = PICKER_LOCALES[i18n.language.slice(0, 2)] ?? ruRU;
  const outOfRange = (key: string) =>
    (min !== undefined && min !== "" && key < min) ||
    (max !== undefined && max !== "" && key > max);

  // rc-picker не принимает набранную дату из отключённых дней и молча возвращает прежнюю — отдаём её форме, пусть скажет словами.
  const commitTyped = (text: string) => {
    const day = dayjs(text.trim(), DATE_INPUT_FORMATS, true);
    if (!day.isValid()) return;
    const key = day.format(ISO);
    if (outOfRange(key) && key !== value) onChange?.(key);
  };

  // rc-picker ставит своё `aria-invalid` (неразобранный ввод) поверх переданного — ошибку формы дописываем после рендера.
  useLayoutEffect(() => {
    const input = ref.current?.nativeElement?.querySelector("input");
    if (!input) return;
    if (invalid) {
      input.setAttribute("aria-invalid", "true");
      marked.current = true;
    } else if (marked.current) {
      input.setAttribute("aria-invalid", "false");
      marked.current = false;
    }
  });

  return (
    <DatePicker
      ref={ref as never}
      id={id}
      className={className}
      style={{ width: "100%", ...style }}
      locale={locale}
      format={DATE_INPUT_FORMATS}
      placeholder={placeholder ?? t("date.placeholder")}
      value={toDay(value)}
      allowClear={allowClear}
      disabled={disabled}
      status={status}
      disabledDate={(day) => outOfRange(day.format(ISO))}
      onChange={(day: Dayjs | null) => {
        onChange?.(day ? day.format(ISO) : "");
      }}
      onKeyDown={(event) => {
        if (event.key !== "Enter") return;
        // Enter фиксирует набранную дату и не отправляет форму (сотрудник ещё не дошёл до главной кнопки)
        event.preventDefault();
        if (event.target instanceof HTMLInputElement) commitTyped(event.target.value);
      }}
      onBlur={(event) => {
        if (event.target instanceof HTMLInputElement) commitTyped(event.target.value);
        onBlur?.();
      }}
      {...aria}
    />
  );
}

export interface DateRange {
  from: string;
  to: string;
}

function DefaultWrap({
  id,
  label,
  children,
  className,
}: {
  id: string;
  label: ReactNode;
  children: ReactNode;
  className?: string | undefined;
}) {
  return (
    <div className={className}>
      <label htmlFor={id}>{label}</label>
      {children}
    </div>
  );
}

/**
 * Пара «с — по» из двух `DateField` с подписями: «с» не позже «по», «по» не раньше «с». Обёртку поля задаёт экран
 * (`wrap`, например `FormField`) или класс `fieldClassName` у обёртки по умолчанию.
 */
export function DateRangeField({
  idFrom,
  idTo,
  value,
  onChange,
  labelFrom,
  labelTo,
  min,
  max,
  disabled,
  fieldClassName,
  style,
  wrap,
}: {
  idFrom: string;
  idTo: string;
  value: DateRange;
  onChange: (next: DateRange) => void;
  labelFrom: ReactNode;
  labelTo: ReactNode;
  min?: string | undefined;
  max?: string | undefined;
  disabled?: boolean | undefined;
  fieldClassName?: string | undefined;
  style?: CSSProperties | undefined;
  wrap?: ((props: { id: string; label: ReactNode; children: ReactNode }) => ReactNode) | undefined;
}) {
  const field = (id: string, label: ReactNode, control: ReactNode) =>
    wrap ? (
      wrap({ id, label, children: control })
    ) : (
      <DefaultWrap id={id} label={label} className={fieldClassName}>
        {control}
      </DefaultWrap>
    );
  return (
    <>
      {field(
        idFrom,
        labelFrom,
        <DateField
          id={idFrom}
          value={value.from}
          min={min}
          max={value.to || max}
          disabled={disabled}
          style={style}
          onChange={(from) => {
            onChange({ ...value, from });
          }}
        />,
      )}
      {field(
        idTo,
        labelTo,
        <DateField
          id={idTo}
          value={value.to}
          min={value.from || min}
          max={max}
          disabled={disabled}
          style={style}
          onChange={(to) => {
            onChange({ ...value, to });
          }}
        />,
      )}
    </>
  );
}
