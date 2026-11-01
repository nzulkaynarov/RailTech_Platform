import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Input, Skeleton } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../../shared/api/errors";
import type { SetupCabinet, SetupCabinetCheck } from "../../../shared/api/generated/model";
import {
  getGetSetupCabinetQueryKey,
  useCheckSetupCabinet,
  useGetSetupCabinet,
  useSaveSetupCabinet,
} from "../../../shared/api/generated/platform-bff";
import { ErrorNote } from "../../../shared/ui/FormParts";
import { Field } from "./parts";

const RESULT_TYPE: Record<SetupCabinetCheck["result"], "success" | "warning" | "error"> = {
  ok: "success",
  not_set: "warning",
  unreachable: "error",
  bad_status: "error",
  not_cabinet: "error",
};

/**
 * «Адрес кабинета клиента» (D17G-3, гейт D1-7): без него приглашение в кабинет и кнопка «Открыть кабинет» под сообщениями
 * бота клиенту не уходят. Один блок для мастера «Первый запуск» и «Подключений»: где сейчас берётся адрес (задан здесь, с
 * сервера — `CABINET_DOMAIN`, или нет), поле, «Проверить доступность» (CRM с сервера открывает `<адрес>/health`) и
 * «Сохранить адрес». Меняет только администратор (`admin` — полный); директору блок не показывается.
 */
export function CabinetAddress({ titled = true }: { titled?: boolean }) {
  const { t } = useTranslation("integrations");
  const address = useGetSetupCabinet();
  const loaded = address.data;
  return (
    <section
      className="pf-int-block"
      {...(titled
        ? { "aria-labelledby": "pf-cabinet-title" }
        : { "aria-label": t("cabinet.title") })}
    >
      {titled ? (
        <h2 id="pf-cabinet-title" className="pf-int-section-title">
          {t("cabinet.title")}
        </h2>
      ) : null}
      <p className="pf-hint" style={{ margin: 0 }}>
        {t("cabinet.lead")}
      </p>
      {loaded ? (
        <CabinetForm key={`${loaded.source}:${loaded.url ?? ""}`} address={loaded} />
      ) : address.isError ? (
        <ErrorNote message={t("cabinet.failed")} />
      ) : (
        <Skeleton active paragraph={{ rows: 2 }} title={false} />
      )}
    </section>
  );
}

function CabinetForm({ address }: { address: SetupCabinet }) {
  const { t } = useTranslation("integrations");
  const { message } = App.useApp();
  const client = useQueryClient();
  const [value, setValue] = useState(address.source === "saved" ? (address.url ?? "") : "");
  const [result, setResult] = useState<SetupCabinetCheck | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const failed = (error: unknown) => {
    setFailure(
      error instanceof ApiError && error.status === 422
        ? t("cabinet.invalid")
        : t("cabinet.failed"),
    );
  };
  const save = useSaveSetupCabinet({
    mutation: {
      onSuccess: (data) => {
        client.setQueryData(getGetSetupCabinetQueryKey(), data);
        void message.success(t("cabinet.saved"));
      },
      onError: failed,
    },
  });
  const check = useCheckSetupCabinet({
    mutation: {
      onSuccess: setResult,
      onError: failed,
    },
  });
  const typed = value.trim();
  return (
    <>
      <p style={{ margin: 0 }} role="status">
        {t(`cabinet.current.${address.source}`, { url: address.url ?? "" })}
      </p>
      <Field id="pf-cabinet-url" label={t("cabinet.label")} hint={t("cabinet.hint")}>
        <Input
          id="pf-cabinet-url"
          value={value}
          inputMode="url"
          autoComplete="off"
          placeholder={address.env_url ?? "https://cabinet.example.com"}
          aria-describedby="pf-cabinet-url-hint"
          onChange={(event) => {
            setValue(event.target.value);
            setResult(null);
            setFailure(null);
          }}
        />
      </Field>
      <div className="pf-int-row">
        <Button
          loading={check.isPending}
          onClick={() => {
            setFailure(null);
            check.mutate({ data: { url: typed === "" ? null : typed } });
          }}
        >
          {t("cabinet.check")}
        </Button>
        <Button
          type="primary"
          loading={save.isPending}
          onClick={() => {
            setFailure(null);
            setResult(null);
            save.mutate({ data: { url: typed } });
          }}
        >
          {t("cabinet.save")}
        </Button>
      </div>
      {result ? (
        <Alert
          type={RESULT_TYPE[result.result]}
          showIcon
          role="status"
          message={t(`cabinet.result.${result.result}`, {
            url: result.url ?? "",
            code: result.status_code ?? "",
          })}
        />
      ) : null}
      <ErrorNote message={failure} />
    </>
  );
}
