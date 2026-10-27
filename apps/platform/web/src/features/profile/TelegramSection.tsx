import { useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Modal, QRCode } from "antd";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { Profile, TelegramLink } from "../../shared/api/generated/model";
import {
  getGetNotificationSettingsQueryKey,
  getGetProfileQueryKey,
  useCreateTelegramLink,
  useDeleteTelegramLink,
  useGetProfile,
} from "../../shared/api/generated/platform-bff";
import { profileErrorText } from "./errors";
import { Section } from "./Section";

const POLL_MS = 3000;

/**
 * «Telegram для уведомлений»: сотрудник привязывает сам. Кнопка выпускает одноразовую ссылку `t.me/<бот>?start=…` на 10
 * минут, окно показывает её кнопкой и QR и опрашивает профиль, пока бот не подтвердит привязку (или срок не выйдет).
 */
export function TelegramSection({ profile }: { profile: Profile }) {
  const { t } = useTranslation("profile");
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const [ticket, setTicket] = useState<TelegramLink | null>(null);
  const [expired, setExpired] = useState(false);
  const watching = ticket !== null && !expired;
  // Тот же запрос профиля, что у страницы; пока окно открыто — опрос.
  useGetProfile({ query: { refetchInterval: watching ? POLL_MS : false } });
  const wasLinked = useRef(profile.telegram.linked);

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: getGetProfileQueryKey() });
    void queryClient.invalidateQueries({ queryKey: getGetNotificationSettingsQueryKey() });
  };
  const create = useCreateTelegramLink({
    mutation: {
      onSuccess: (next) => {
        setExpired(false);
        setTicket(next);
      },
    },
  });
  const unlink = useDeleteTelegramLink({
    mutation: {
      onSuccess: (next) => {
        queryClient.setQueryData(getGetProfileQueryKey(), next);
        refresh();
        void message.success(t("telegram.unlinked"));
      },
    },
  });

  // Бот подтвердил привязку: закрыть окно.
  useEffect(() => {
    if (profile.telegram.linked && !wasLinked.current && ticket) {
      setTicket(null);
      refresh();
      void message.success(t("telegram.doneLinked"));
    }
    wasLinked.current = profile.telegram.linked;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- реагируем только на смену признака привязки
  }, [profile.telegram.linked]);

  // Срок ссылки вышел — показать «получите новую».
  useEffect(() => {
    if (!ticket) return;
    const left = new Date(ticket.expires_at).getTime() - Date.now();
    const timer = window.setTimeout(
      () => {
        setExpired(true);
      },
      Math.max(0, left),
    );
    return () => {
      window.clearTimeout(timer);
    };
  }, [ticket]);

  const linked = profile.telegram.linked;
  const username = profile.telegram.username;
  const status = linked
    ? username
      ? t("telegram.linkedAs", { name: username })
      : t("telegram.linked")
    : t("telegram.notLinked");
  const error = create.isError
    ? profileErrorText(t, "telegram", create.error)
    : unlink.isError
      ? profileErrorText(t, "telegram", unlink.error)
      : null;

  const confirmUnlink = () => {
    modal.confirm({
      title: t("telegram.unlinkTitle"),
      content: t("telegram.unlinkText"),
      okText: t("telegram.unlinkConfirm"),
      cancelText: t("telegram.unlinkCancel"),
      okButtonProps: { danger: true },
      onOk: () =>
        unlink.mutateAsync().then(
          () => undefined,
          () => undefined,
        ),
    });
  };

  return (
    <Section title={t("telegram.title")} lead={t("telegram.lead")} testId="profile-telegram">
      <div className="pf-profile-status">
        <strong>{status}</strong>
      </div>
      {error ? (
        <Alert type="error" showIcon role="alert" message={error} style={{ marginBottom: 12 }} />
      ) : null}
      {linked ? (
        <Button onClick={confirmUnlink} loading={unlink.isPending}>
          {t("telegram.unlink")}
        </Button>
      ) : (
        <Button
          loading={create.isPending}
          onClick={() => {
            create.mutate();
          }}
        >
          {t("telegram.link")}
        </Button>
      )}

      <Modal
        open={ticket !== null}
        title={t("telegram.modalTitle")}
        onCancel={() => {
          setTicket(null);
        }}
        destroyOnHidden
        width={360}
        footer={
          <Button
            onClick={() => {
              setTicket(null);
            }}
          >
            {t("telegram.close")}
          </Button>
        }
      >
        {ticket ? (
          <div className="pf-profile-qr">
            <p style={{ margin: 0 }}>{t("telegram.step1")}</p>
            {expired ? (
              <>
                <Alert type="warning" showIcon message={t("telegram.expired")} />
                <Button
                  loading={create.isPending}
                  onClick={() => {
                    create.mutate();
                  }}
                >
                  {t("telegram.again")}
                </Button>
              </>
            ) : (
              <>
                <div role="img" aria-label={t("telegram.qrLabel")}>
                  {/* Имя картинке даёт обёртка; сам svg для скринридера скрыт (он без подписи) */}
                  <div aria-hidden="true">
                    <QRCode type="svg" value={ticket.url} size={176} bordered={false} />
                  </div>
                </div>
                <Button type="primary" href={ticket.url} target="_blank" rel="noopener noreferrer">
                  {t("telegram.open")}
                </Button>
                <p className="pf-hint" style={{ margin: 0 }}>
                  {t("telegram.step2")}
                </p>
                <p className="pf-hint" role="status" style={{ margin: 0 }}>
                  {t("telegram.waiting")} {t("telegram.validFor")}
                </p>
              </>
            )}
          </div>
        ) : null}
      </Modal>
    </Section>
  );
}
