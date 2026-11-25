import { Alert, App, Button } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useId, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { employeeErrorText } from "../../entities/employee/errors";
import type { Employee } from "../../shared/api/generated/model";
import { useListEmployees } from "../../shared/api/generated/platform-bff";
import { useFormat } from "../../shared/lib/useFormat";
import { useEmployeeUpdate } from "../assign-role/useEmployeeMutations";
import { DEPUTY_ISO as ISO, DeputyFields } from "../profile/DeputyFields";

import "../profile/profile.css";

export interface EmployeeDeputyProps {
  employee: Employee;
  /** `Me.id` администратора, который работает с карточкой */
  selfId: string;
}

/**
 * «Замещение» в карточке сотрудника (СОТР-1): администратор ставит и снимает замещение за того, кто сам не может (болен, не
 * вошёл) — его задачи, визы и резолюции не стоят. Те же три поля, что в «Профиле · Замещение»; правила периода, «себя
 * нельзя» и журнал (`user.deputy_set` / `user.deputy_cleared`) — в CRM, как и у профиля.
 */
export function EmployeeDeputy({ employee, selfId }: EmployeeDeputyProps) {
  const { t } = useTranslation(["modules", "profile"]);
  const { message } = App.useApp();
  const format = useFormat();
  const base = useId();
  const colleagues = useListEmployees();
  const deputy = employee.deputy;
  const [who, setWho] = useState<string | undefined>(deputy?.user_id);
  const [from, setFrom] = useState<Dayjs | null>(deputy ? dayjs(deputy.date_from) : null);
  const [to, setTo] = useState<Dayjs | null>(deputy ? dayjs(deputy.date_to) : null);
  const [incomplete, setIncomplete] = useState(false);

  const options = useMemo(
    () =>
      (colleagues.data?.items ?? [])
        .filter((e) => e.id !== employee.id && e.status !== "disabled")
        .map((e) => ({ id: e.id, name: e.name, position: e.position })),
    [colleagues.data, employee.id],
  );
  // Имя пришло пустым (CRM не дала его) — берём из списка сотрудников
  const deputyName = deputy
    ? deputy.name || options.find((o) => o.id === deputy.user_id)?.name
    : "";

  const reset = (next: Employee) => {
    setWho(next.deputy?.user_id);
    setFrom(next.deputy ? dayjs(next.deputy.date_from) : null);
    setTo(next.deputy ? dayjs(next.deputy.date_to) : null);
    setIncomplete(false);
  };
  const update = useEmployeeUpdate(selfId);
  const save = () => {
    if (!who || !from || !to) {
      setIncomplete(true);
      return;
    }
    setIncomplete(false);
    update.mutate(
      {
        id: employee.id,
        data: {
          deputy: { deputy_id: who, date_from: from.format(ISO), date_to: to.format(ISO) },
        },
      },
      {
        onSuccess: (next) => {
          reset(next);
          void message.success(t("profile:deputy.saved"));
        },
      },
    );
  };
  const clear = () => {
    update.mutate(
      { id: employee.id, data: { deputy: null } },
      {
        onSuccess: (next) => {
          reset(next);
          void message.success(t("profile:deputy.cleared"));
        },
      },
    );
  };
  const dirty =
    who !== deputy?.user_id ||
    (from ? from.format(ISO) : null) !== (deputy?.date_from ?? null) ||
    (to ? to.format(ISO) : null) !== (deputy?.date_to ?? null);

  return (
    <section
      className="pf-panel-stack"
      aria-labelledby={`${base}-title`}
      data-testid="employee-deputy"
    >
      <h4
        id={`${base}-title`}
        style={{ margin: 0, fontSize: 14, lineHeight: "22px", fontWeight: 600 }}
      >
        {t("modules:admin.org.deputy.title")}
      </h4>
      <p style={{ margin: 0 }} data-testid="employee-deputy-sentence">
        {deputy
          ? t("modules:admin.org.deputy.sentence", {
              name: deputyName,
              from: format.date(deputy.date_from, "date"),
              to: format.date(deputy.date_to, "date"),
            })
          : t("modules:admin.org.deputy.none")}
      </p>
      {incomplete ? (
        <Alert type="error" showIcon role="alert" message={t("profile:deputy.required")} />
      ) : null}
      {update.isError ? (
        <Alert type="error" showIcon role="alert" message={employeeErrorText(t, update.error)} />
      ) : null}
      <DeputyFields
        base={base}
        who={who}
        from={from}
        to={to}
        options={options}
        loading={colleagues.isPending}
        onWho={setWho}
        onFrom={setFrom}
        onTo={setTo}
      />
      <Button type="primary" block loading={update.isPending} disabled={!dirty} onClick={save}>
        {deputy ? t("profile:deputy.change") : t("profile:deputy.set")}
      </Button>
      {deputy ? (
        <Button danger block disabled={update.isPending} onClick={clear}>
          {t("profile:deputy.clear")}
        </Button>
      ) : null}
    </section>
  );
}
