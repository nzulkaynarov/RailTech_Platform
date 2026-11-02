import { Input, Select } from "antd";
import { useTranslation } from "react-i18next";

import type { OnBehalfChannel } from "../api/generated/model";
import { ON_BEHALF_CHANNELS } from "../lib/onBehalf";
import { FormField } from "./FormParts";
import { StatusTag } from "./StatusTag";

import "./ui.css";

/**
 * Значок «Отмечено сотрудником» (A1, A2 волны 18a): действие контрагента записал сотрудник — кто записал, канал и лицо со
 * стороны клиента. Отличает запись сотрудника от онлайн-действия клиента в кабинете (эталон — Stripe `paid_out_of_band`).
 */
export function OnBehalfNote({
  channel,
  person,
  staff,
}: {
  channel: OnBehalfChannel;
  person: string;
  staff?: string | null | undefined;
}) {
  const { t } = useTranslation("ui");
  const parts = [
    staff ? t("onBehalf.staff", { name: staff }) : null,
    t(`onBehalf.channel.${channel}`),
    t("onBehalf.person", { person }),
  ].filter(Boolean);
  return (
    <span className="pf-onbehalf">
      <StatusTag tone="gold">{t("onBehalf.tag")}</StatusTag>
      <span className="pf-hint">{parts.join(" · ")}</span>
    </span>
  );
}

/** Канал и лицо со стороны клиента — общая часть форм «Клиент принял / отклонил КП» и «Согласован клиентом». */
export function OnBehalfFields({
  ids,
  channel,
  person,
  touched,
  onChannel,
  onPerson,
}: {
  ids: { channel: string; person: string };
  channel: OnBehalfChannel | null;
  person: string;
  touched: boolean;
  onChannel: (value: OnBehalfChannel) => void;
  onPerson: (value: string) => void;
}) {
  const { t } = useTranslation("ui");
  const noChannel = touched && channel === null;
  const noPerson = touched && !person.trim();
  return (
    <>
      <FormField
        id={ids.channel}
        label={t("onBehalf.channelLabel")}
        hint={noChannel ? t("onBehalf.channelRequired") : undefined}
      >
        <Select
          id={ids.channel}
          status={noChannel ? "error" : undefined}
          placeholder={t("onBehalf.channelPlaceholder")}
          value={channel}
          onChange={onChannel}
          options={ON_BEHALF_CHANNELS.map((value) => ({
            value,
            label: t(`onBehalf.channel.${value}`),
          }))}
          style={{ width: "100%" }}
        />
      </FormField>
      <FormField
        id={ids.person}
        label={t("onBehalf.personLabel")}
        hint={noPerson ? t("onBehalf.personRequired") : undefined}
      >
        <Input
          id={ids.person}
          aria-required
          status={noPerson ? "error" : undefined}
          maxLength={200}
          placeholder={t("onBehalf.personPlaceholder")}
          value={person}
          onChange={(event) => {
            onPerson(event.target.value);
          }}
        />
      </FormField>
    </>
  );
}
