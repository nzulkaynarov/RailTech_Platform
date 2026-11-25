import { DatePicker } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useTranslation } from "react-i18next";

import { EmployeePicker, type EmployeeOption } from "../../shared/ui/EmployeePicker";

export const DEPUTY_DATE_FORMAT = "DD.MM.YYYY";
export const DEPUTY_ISO = "YYYY-MM-DD";

interface DeputyFieldsProps {
  /** Префикс id полей: подписи привязаны к ним */
  base: string;
  who: string | undefined;
  from: Dayjs | null;
  to: Dayjs | null;
  options: readonly EmployeeOption[];
  loading?: boolean;
  onWho: (id: string | undefined) => void;
  onFrom: (day: Dayjs | null) => void;
  onTo: (day: Dayjs | null) => void;
}

/**
 * Три поля замещения: «Кто замещает», «С даты», «По дату». Одни и те же в «Профиле» (сам сотрудник) и в карточке сотрудника
 * (администратор, СОТР-1): слова — из словаря профиля, правила периода проверяет CRM.
 */
export function DeputyFields({
  base,
  who,
  from,
  to,
  options,
  loading,
  onWho,
  onFrom,
  onTo,
}: DeputyFieldsProps) {
  const { t } = useTranslation("profile");
  const today = dayjs().startOf("day");
  return (
    <div className="pf-profile-deputy-row">
      <div>
        <label htmlFor={`${base}-who`}>{t("deputy.who")}</label>
        <EmployeePicker
          id={`${base}-who`}
          value={who}
          options={options}
          onChange={onWho}
          loading={loading}
          placeholder={t("deputy.whoPlaceholder")}
          emptyText={t("deputy.noCandidates")}
          allowClear={false}
        />
      </div>
      <div>
        <label htmlFor={`${base}-from`}>{t("deputy.from")}</label>
        <DatePicker
          id={`${base}-from`}
          style={{ width: "100%" }}
          format={DEPUTY_DATE_FORMAT}
          value={from}
          allowClear={false}
          disabledDate={(day) => day.isBefore(today)}
          onChange={(day) => {
            onFrom(day);
            if (to?.isBefore(day)) onTo(null);
          }}
        />
      </div>
      <div>
        <label htmlFor={`${base}-to`}>{t("deputy.to")}</label>
        <DatePicker
          id={`${base}-to`}
          style={{ width: "100%" }}
          format={DEPUTY_DATE_FORMAT}
          value={to}
          allowClear={false}
          disabledDate={(day) => day.isBefore(from ?? today)}
          onChange={onTo}
        />
      </div>
    </div>
  );
}
