import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, DatePicker, Select } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type { Profile } from "../../shared/api/generated/model";
import {
  getGetProfileQueryKey,
  useClearDeputy,
  useListDeputyCandidates,
  useSetDeputy,
} from "../../shared/api/generated/platform-bff";
import { useFormat } from "../../shared/lib/useFormat";
import { profileErrorText } from "./errors";
import { Section } from "./Section";

const DATE_FORMAT = "DD.MM.YYYY";
const ISO = "YYYY-MM-DD";

/**
 * «Замещение»: «На время отсутствия мои задачи видит {сотрудник} с {дата} по {дата}». Данные — в CRM; заместитель видит
 * очередь строками «за {имя}», права на объекты у него свои. Ниже — те, за кого замещает сам сотрудник.
 */
export function DeputySection({ profile }: { profile: Profile }) {
  const { t } = useTranslation("profile");
  const { message } = App.useApp();
  const format = useFormat();
  const queryClient = useQueryClient();
  const base = useId();
  const candidates = useListDeputyCandidates();
  const deputy = profile.deputy;
  const [who, setWho] = useState<string | undefined>(deputy?.user_id);
  const [from, setFrom] = useState<Dayjs | null>(deputy ? dayjs(deputy.date_from) : null);
  const [to, setTo] = useState<Dayjs | null>(deputy ? dayjs(deputy.date_to) : null);
  const [incomplete, setIncomplete] = useState(false);

  const done = (next: Profile, text: string) => {
    queryClient.setQueryData(getGetProfileQueryKey(), next);
    void message.success(text);
  };
  const set = useSetDeputy({
    mutation: {
      onSuccess: (next) => {
        done(next, t("deputy.saved"));
      },
    },
  });
  const clear = useClearDeputy({
    mutation: {
      onSuccess: (next) => {
        setWho(undefined);
        setFrom(null);
        setTo(null);
        done(next, t("deputy.cleared"));
      },
    },
  });

  const submit = () => {
    if (!who || !from || !to) {
      setIncomplete(true);
      return;
    }
    setIncomplete(false);
    set.mutate({
      data: { deputy_id: who, date_from: from.format(ISO), date_to: to.format(ISO) },
    });
  };
  const today = dayjs().startOf("day");
  const error = set.isError
    ? profileErrorText(t, "deputy", set.error)
    : clear.isError
      ? profileErrorText(t, "deputy", clear.error)
      : incomplete
        ? t("deputy.required")
        : null;

  return (
    <Section title={t("deputy.title")} lead={t("deputy.lead")} testId="profile-deputy">
      <p style={{ margin: "0 0 12px" }} data-testid="deputy-sentence">
        {deputy
          ? t("deputy.sentence", {
              name: deputy.name,
              from: format.date(deputy.date_from, "date"),
              to: format.date(deputy.date_to, "date"),
            })
          : t("deputy.none")}
      </p>
      {error ? (
        <Alert type="error" showIcon role="alert" message={error} style={{ marginBottom: 12 }} />
      ) : null}
      <div className="pf-profile-deputy-row">
        <div>
          <label htmlFor={`${base}-who`}>{t("deputy.who")}</label>
          <Select
            id={`${base}-who`}
            style={{ width: "100%" }}
            placeholder={t("deputy.whoPlaceholder")}
            value={who}
            onChange={setWho}
            loading={candidates.isPending}
            notFoundContent={candidates.isSuccess ? t("deputy.noCandidates") : undefined}
            options={(candidates.data ?? []).map((c) => ({
              value: c.id,
              label: c.position ? `${c.name} · ${c.position}` : c.name,
            }))}
          />
        </div>
        <div>
          <label htmlFor={`${base}-from`}>{t("deputy.from")}</label>
          <DatePicker
            id={`${base}-from`}
            style={{ width: "100%" }}
            format={DATE_FORMAT}
            value={from}
            allowClear={false}
            disabledDate={(day) => day.isBefore(today)}
            onChange={(day) => {
              setFrom(day);
              if (to?.isBefore(day)) setTo(null);
            }}
          />
        </div>
        <div>
          <label htmlFor={`${base}-to`}>{t("deputy.to")}</label>
          <DatePicker
            id={`${base}-to`}
            style={{ width: "100%" }}
            format={DATE_FORMAT}
            value={to}
            allowClear={false}
            disabledDate={(day) => day.isBefore(from ?? today)}
            onChange={setTo}
          />
        </div>
      </div>
      <div className="pf-profile-actions">
        <Button loading={set.isPending} onClick={submit}>
          {deputy ? t("deputy.change") : t("deputy.set")}
        </Button>
        {deputy ? (
          <Button
            danger
            loading={clear.isPending}
            onClick={() => {
              clear.mutate();
            }}
          >
            {t("deputy.clear")}
          </Button>
        ) : null}
      </div>
      {profile.covering.length > 0 ? (
        <ul style={{ margin: "16px 0 0", paddingLeft: 20 }} data-testid="covering-list">
          {profile.covering.map((c) => (
            <li key={c.user_id}>
              {t("deputy.covering", {
                name: c.name,
                from: format.date(c.date_from, "date"),
                to: format.date(c.date_to, "date"),
              })}
            </li>
          ))}
        </ul>
      ) : null}
    </Section>
  );
}
