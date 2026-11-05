import { SyncOutlined } from "@ant-design/icons";
import { Button } from "antd";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import type { InboundMailCheck } from "../../../shared/api/generated/model";
import { useCheckInboundMail } from "../../../shared/api/generated/platform-bff";
import { formatDate } from "../../../shared/lib/dates";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { ADMIN_MAIL_PATH, minutesSince, useRefreshMail } from "./mailModel";

const TICK_MS = 30_000;
/** Итог проверки висит коротко: через это время строка очищается (слот остаётся — без сдвига). */
const RESULT_MS = 15_000;
/** «Проверка идёт в фоне»: письма доезжают сами, список перечитывается один раз позже. */
const BACKGROUND_REFRESH_MS = 8_000;

/** Раз в полминуты — чтобы «Проверено N мин назад» не застывало на открытом экране. */
function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => {
      setNow(Date.now());
    }, TICK_MS);
    return () => {
      window.clearInterval(timer);
    };
  }, []);
  return now;
}

type Outcome = Pick<InboundMailCheck, "status" | "created" | "error_kind" | "retry_after_s">;
const FAILED: Outcome = { status: "error", created: 0, error_kind: "request", retry_after_s: null };

/**
 * «Проверить почту» (MAIL-NOW): строка «Проверено N мин назад» по `mailbox.last_poll_at` и кнопка немедленного опроса
 * ящика (эталон — «Получить сообщения» в Thunderbird, «Отправить и получить» в Outlook). Итог — одной короткой строкой
 * с `role="status"`; после успешной проверки список перечитывается сам. На узком экране у кнопки остаётся иконка,
 * подпись — для экранного диктора.
 */
export function MailCheck({
  lastPollAt,
  configured,
}: {
  lastPollAt: string | null;
  configured: boolean;
}) {
  const { t, i18n } = useTranslation("letters");
  const { me } = useAuth();
  const refresh = useRefreshMail();
  const now = useNow();
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const clearTimer = useRef<number | undefined>(undefined);
  const laterTimer = useRef<number | undefined>(undefined);
  const check = useCheckInboundMail();
  useEffect(
    () => () => {
      window.clearTimeout(clearTimer.current);
      window.clearTimeout(laterTimer.current);
    },
    [],
  );
  const show = (next: Outcome) => {
    setOutcome(next);
    window.clearTimeout(clearTimer.current);
    clearTimer.current = window.setTimeout(() => {
      setOutcome(null);
    }, RESULT_MS);
  };
  const run = () => {
    setOutcome(null);
    check.mutate(undefined, {
      onSuccess: (result) => {
        show(result);
        if (result.status === "ok") void refresh();
        if (result.status === "checking") {
          window.clearTimeout(laterTimer.current);
          laterTimer.current = window.setTimeout(() => {
            void refresh();
          }, BACKGROUND_REFRESH_MS);
        }
      },
      onError: () => {
        show(FAILED);
      },
    });
  };
  const minutes = lastPollAt ? minutesSince(lastPollAt, now) : null;
  let checked: string | null = null;
  if (configured && minutes === null) checked = t("mail.check.never");
  else if (minutes !== null) {
    if (minutes < 1) checked = t("mail.check.justNow");
    else if (minutes < 60) checked = t("mail.check.minutes", { count: minutes });
    else if (minutes < 24 * 60)
      checked = t("mail.check.hours", { count: Math.floor(minutes / 60) });
    else
      checked = t("mail.check.date", { date: formatDate(lastPollAt, { language: i18n.language }) });
  }
  return (
    <div className="pf-mail-check">
      <div className="pf-mail-check-row">
        {checked ? <span className="pf-hint pf-mail-checked">{checked}</span> : null}
        <Button
          icon={<SyncOutlined spin={check.isPending} />}
          aria-busy={check.isPending}
          aria-label={check.isPending ? t("mail.check.busy") : t("mail.check.button")}
          disabled={check.isPending}
          onClick={run}
        >
          <span className="pf-mail-check-text">
            {check.isPending ? t("mail.check.busy") : t("mail.check.button")}
          </span>
        </Button>
      </div>
      <div
        className="pf-mail-check-result"
        role="status"
        aria-live="polite"
        aria-label={t("mail.check.resultLabel")}
      >
        {outcome ? (
          <CheckResult outcome={outcome} admin={canSee(me, { resource: "admin" })} />
        ) : null}
      </div>
    </div>
  );
}

function CheckResult({ outcome, admin }: { outcome: Outcome; admin: boolean }) {
  const { t } = useTranslation("letters");
  const settings = t("mail.check.settings");
  const link = admin ? (
    <LinkButton type="link" size="small" to={ADMIN_MAIL_PATH}>
      {settings}
    </LinkButton>
  ) : (
    <span>{settings}</span>
  );
  switch (outcome.status) {
    case "ok":
      return outcome.created > 0 ? (
        <span>{t("mail.check.found", { count: outcome.created })}</span>
      ) : (
        <span>{t("mail.check.none")}</span>
      );
    case "off":
      return (
        <span>
          {t("mail.check.off")} {link}
        </span>
      );
    case "checking":
      return <span>{t("mail.check.checking")}</span>;
    case "too_soon":
      return <span>{t("mail.check.tooSoon", { count: outcome.retry_after_s ?? 20 })}</span>;
    default: {
      const kind = outcome.error_kind;
      if (kind === "auth_failed" || kind === "mailbox_missing")
        return (
          <span>
            {t(`mail.check.error.${kind}`)} — {link}
          </span>
        );
      return <span>{t("mail.check.error.default")}</span>;
    }
  }
}
