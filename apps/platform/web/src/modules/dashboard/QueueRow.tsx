import { App, Button } from "antd";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";

import type { QueueItem } from "../../shared/api/generated/model";
import { useAcknowledgeLetter, useTakeCrmLead } from "../../shared/api/generated/platform-bff";
import { useFormat } from "../../shared/lib/useFormat";
import { LinkButton } from "../../shared/ui/LinkButton";
import { StatusTag } from "../../shared/ui/StatusTag";
import { objectLink } from "../objectLinks";
import { dueBadge, isUrgent } from "./queue";
import { actionKeyOf, acquaintLetterId, quickActionOf } from "./queueModel";

/** Строки очереди и меню после быстрого действия перечитываются; источник строки сам погасит её. */
function useRefreshQueue(): () => void {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({
      predicate: (query) => {
        const head = String(query.queryKey[0]);
        return (
          head.startsWith("/api/v1/queue") ||
          head.startsWith("/api/v1/menu-counters") ||
          head.startsWith("/api/v1/eds/letters") ||
          head.startsWith("/api/v1/crm/")
        );
      },
    });
  };
}

/**
 * Строка «Что ждёт вас» (ГЛ-1): срок, заголовок, «Почему у вас: …» из факта источника и кнопка с названием действия.
 * Быстрое действие в самой строке — только простое («Ознакомлен», «Взять»); остальное открывает объект, где решение.
 */
export function QueueRow({ item }: { item: QueueItem }) {
  const { t } = useTranslation(["modules", "ui"]);
  const format = useFormat();
  const { message } = App.useApp();
  const refresh = useRefreshQueue();
  const navigate = useNavigate();
  const acknowledge = useAcknowledgeLetter();
  const take = useTakeCrmLead();
  const quick = quickActionOf(item);
  const actionKey = actionKeyOf(item);
  // Подпись кнопки — из i18n по виду строки; глагол BFF — запасной вариант для вида без ключа
  const action = actionKey
    ? t(`modules:dashboard.queue.actions.${actionKey}`)
    : (item.action_label ?? t("ui:open"));
  const badge = dueBadge(
    item,
    (key, options) => t(key, options),
    (value) => format.date(value, "short"),
  );
  const label = t("modules:dashboard.queue.openLabel", { action, title: item.title });
  const onSuccess = (text: string) => () => {
    void message.success(text);
    refresh();
  };
  const onError = () => {
    void message.error(t("modules:dashboard.queue.quick.failed"));
  };
  // Без `reason` (старый ответ BFF) строка «за {имя}» остаётся помеченной, как раньше
  const caption =
    !item.reason && item.on_behalf_of
      ? `${t("modules:dashboard.queue.onBehalf", { name: item.on_behalf_of.name })} · ${item.subtitle}`
      : item.subtitle;
  return (
    <li className="pf-queue-row">
      <StatusTag kind="due" status={item.due_label}>
        {badge.label}
      </StatusTag>
      <div className="pf-queue-body">
        <div className="pf-queue-title">{item.title}</div>
        {item.reason ? (
          <div className="pf-queue-why">
            <span className="pf-hint">{t("modules:dashboard.queue.why")}</span> {item.reason}
          </div>
        ) : null}
        {caption ? <div className="pf-hint">{caption}</div> : null}
      </div>
      {quick === "acknowledge" ? (
        <Button
          aria-label={label}
          loading={acknowledge.isPending}
          onClick={() => {
            acknowledge.mutate(
              { id: acquaintLetterId(item.id) },
              { onSuccess: onSuccess(t("modules:dashboard.queue.quick.acknowledged")), onError },
            );
          }}
        >
          {action}
        </Button>
      ) : quick === "take" ? (
        <Button
          aria-label={label}
          loading={take.isPending}
          onClick={() => {
            take.mutate(
              { lead: item.object.number },
              {
                onSuccess: () => {
                  onSuccess(t("modules:dashboard.queue.quick.taken"))();
                  // как «Забрать» в «Лидах»: взяли — сразу в диалог с клиентом
                  void navigate(objectLink(item.object));
                },
                onError,
              },
            );
          }}
        >
          {action}
        </Button>
      ) : (
        <LinkButton
          to={objectLink(item.object)}
          type={isUrgent(item) ? "primary" : "default"}
          aria-label={label}
        >
          {action}
        </LinkButton>
      )}
    </li>
  );
}
