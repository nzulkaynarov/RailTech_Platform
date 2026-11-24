import { App, Button, Card } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useFormat } from "../lib/useFormat";
import type { ClientLinkKind, ClientLinkRow, ClientLinkState } from "./clientLinkState";
import { useConfirmAction } from "./useConfirmAction";

interface Props {
  kind: ClientLinkKind;
  state: ClientLinkState;
  /** Когда гаснет самая поздняя живая ссылка; нет — «Ссылка действует.» */
  expiresAt: string | null;
  rows: readonly ClientLinkRow[];
  canRevoke: boolean;
  /** Отзыв на сервере; ошибка — отказ (сообщение показывает блок), успех — обновить данные экрана. */
  onRevoke: () => Promise<unknown>;
}

/**
 * Ссылка клиента на документ в Кабинете (ДК-1, ДК-3б): действует ли, кому ушла (адрес замаскирован), открывал ли клиент.
 * Тот, кто отправляет документ, может её отозвать — клиент по ней увидит только «ссылка отозвана»; новая отправка даёт
 * новую ссылку. Отзыв необратим для этой ссылки, поэтому спрашиваем один раз. Один блок для КП, договора, счёта и акта.
 */
export function ClientLinkBlock({ kind, state, expiresAt, rows, canRevoke, onRevoke }: Props) {
  const { t } = useTranslation("ui");
  // ДК-5: у запроса цены и заказа поставщику получатель — партнёр, а не клиент: свои слова в заголовке и строках
  const partner = kind === "price_request" || kind === "supplier_order";
  const who = partner ? "partner" : undefined;
  const { date } = useFormat();
  const { message } = App.useApp();
  const confirmAction = useConfirmAction();
  const [busy, setBusy] = useState(false);

  const confirmRevoke = () => {
    confirmAction({
      action: t("clientLink.confirmAction"),
      object: t("clientLink.confirmObject", { context: kind }),
      summary: t("clientLink.confirmText", {
        context: partner ? "partner" : kind === "quote" ? "quote" : "",
      }),
      danger: true,
      onConfirm: () => {
        setBusy(true);
        onRevoke()
          .then(() => {
            void message.success(t("clientLink.done"));
          })
          .catch(() => {
            void message.error(t("clientLink.failed"));
          })
          .finally(() => {
            setBusy(false);
          });
      },
    });
  };

  // «Ссылки нет» — только у state=none; живая ссылка без срока — просто «действует».
  const line =
    state === "revoked"
      ? t("clientLink.state.revoked", {
          context: partner ? "partner" : kind === "quote" ? "quote" : "",
        })
      : state !== "active"
        ? t(`clientLink.state.${state}`)
        : expiresAt
          ? t("clientLink.state.active", { date: date(expiresAt, "date") })
          : t("clientLink.state.activeNoDate");
  const several = rows.length > 1;
  return (
    <Card
      size="small"
      title={<h2 className="pf-dec-title">{t("clientLink.title", { context: who })}</h2>}
    >
      <p className="pf-dec-note">{line}</p>
      {rows.map((row) => (
        <div key={row.key} className={several ? "pf-doc-link-row" : undefined}>
          {row.hint ? <p className="pf-hint">{t("clientLink.to", { to: row.hint })}</p> : null}
          {row.sentAt ? (
            <p className="pf-hint">
              {t("clientLink.sent", { date: date(row.sentAt, "datetime") })}
            </p>
          ) : null}
          {state !== "none" ? (
            <p className="pf-hint">
              {row.openedAt
                ? t("clientLink.opened", { date: date(row.openedAt, "datetime"), context: who })
                : t("clientLink.notOpened", { context: who })}
            </p>
          ) : null}
          {several && row.state && row.state !== "active" ? (
            <p className="pf-hint">{t(`clientLink.rowState.${row.state}`)}</p>
          ) : null}
        </div>
      ))}
      {canRevoke ? (
        <div className="pf-dec-row">
          <Button danger loading={busy} onClick={confirmRevoke}>
            {t("clientLink.revoke")}
          </Button>
        </div>
      ) : null}
    </Card>
  );
}

/** Список ссылок не загрузился: блок не пропадает молча — сотрудник должен знать, что ссылки могли уйти. */
export function ClientLinkLoadError({
  onRetry,
  partner = false,
}: {
  onRetry: () => void;
  partner?: boolean;
}) {
  const { t } = useTranslation("ui");
  const context = partner ? "partner" : undefined;
  return (
    <Card
      size="small"
      title={<h2 className="pf-dec-title">{t("clientLink.title", { context })}</h2>}
    >
      <p className="pf-dec-note" role="alert">
        {t("clientLink.loadFailed", { context })}
      </p>
      <div className="pf-dec-row">
        <Button onClick={onRetry}>{t("clientLink.retry")}</Button>
      </div>
    </Card>
  );
}
