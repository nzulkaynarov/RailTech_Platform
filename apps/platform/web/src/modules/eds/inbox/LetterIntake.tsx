import { Alert, Button } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { ApiError } from "../../../shared/api/errors";
import type { LetterCard } from "../../../shared/api/generated/model";
import { completeInstruction } from "../../../shared/api/generated/platform-bff";
import { useNotify } from "../../../shared/notify/NotifyProvider";
import { DisabledReason } from "../../../shared/ui/DisabledReason";
import { PartnerDialog, RequestSheet } from "../tasks/LetterOutcomes";
import { useRefreshLetters } from "./api";

type Kind = "request" | "partner";

/** Письма, по которым работа не ведётся: у каждого своя причина на экране */
const NOT_WORKED = new Set(["closed", "duplicate", "rejected", "returned"]);

/**
 * Что можно создать из письма (ВХОД-1): «Заявка клиента» и «Подключение партнёра» — действия карточки, а не пункты меню
 * поручения. Резолюция для них не обязательна: письмо в работе, если его не закрыли, не отклонили и не признали дублем.
 * Недоступное действие стоит на месте и называет причину; поручение ответственного (если оно у вас) закрывается ссылкой
 * на созданное, как при «Передать в работу».
 */
export function LetterIntake({ letter }: { letter: LetterCard }) {
  const { t } = useTranslation("letters");
  const { me } = useAuth();
  const notify = useNotify();
  const refresh = useRefreshLetters();
  const [open, setOpen] = useState<Kind | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Заявка создана из этой карточки: письмо ещё не обновилось (номер ЗВ даёт ERP позже), а вторая заявка не нужна
  const [requestMade, setRequestMade] = useState(false);

  const mine = (letter.instructions ?? []).find(
    (i) => i.role === "responsible" && i.status === "in_work" && i.person.id === me.id,
  );
  const can: Record<Kind, boolean> = {
    request: canEdit(me, "crm.clients"),
    partner: canEdit(me, "erp.stock"),
  };
  const reason = (kind: Kind): string | null => {
    if (!can[kind]) return t(`intake.reason.noRight.${kind}`);
    if (NOT_WORKED.has(letter.status)) return t(`intake.reason.status.${letter.status}`);
    if (kind === "request" && requestMade && !letter.request) return t("intake.reason.requestMade");
    if (kind === "request" && letter.request) {
      return t("intake.reason.hasRequest", { number: letter.request.number });
    }
    return null;
  };
  const requestReason = reason("request");
  const partnerReason = reason("partner");

  const finish = async (kind: Kind, id: string) => {
    if (kind === "request") setRequestMade(true);
    if (mine) {
      await completeInstruction(mine.id, {
        handed_to: { kind: kind === "request" ? "client_request" : "partner_application", id },
      });
    }
    notify.success(t(`intake.done.${kind}`, { number: letter.number }));
    await refresh();
  };

  return (
    <section className="pf-card pf-letter-intake" aria-label={t("intake.title")}>
      <h2 className="pf-letters-title">{t("intake.title")}</h2>
      <div className="pf-letter-intake__actions">
        <div className="pf-letter-intake__action">
          <Button
            disabled={requestReason !== null}
            aria-describedby={requestReason ? "intake-request-reason" : undefined}
            onClick={() => {
              setError(null);
              setOpen("request");
            }}
          >
            {t("intake.request")}
          </Button>
          <DisabledReason id="intake-request-reason">{requestReason}</DisabledReason>
        </div>
        <div className="pf-letter-intake__action">
          <Button
            disabled={partnerReason !== null}
            aria-describedby={partnerReason ? "intake-partner-reason" : undefined}
            onClick={() => {
              setError(null);
              setOpen("partner");
            }}
          >
            {t("intake.partner")}
          </Button>
          <DisabledReason id="intake-partner-reason">{partnerReason}</DisabledReason>
        </div>
      </div>
      {open === "request" ? (
        <RequestSheet
          letter={letter}
          title={t("intake.requestTitle", { number: letter.number })}
          error={error}
          onClose={() => {
            setOpen(null);
          }}
          onCreated={(result) => {
            finish("request", String(result.deal)).catch((failure: unknown) => {
              setError(
                failure instanceof ApiError
                  ? failure.message || t("outcome.failed")
                  : t("outcome.failed"),
              );
            });
          }}
        />
      ) : null}
      {open === "partner" ? (
        <PartnerDialog
          letter={letter}
          onClose={() => {
            setOpen(null);
          }}
          onCreated={async (id) => {
            await finish("partner", id);
            setOpen(null);
          }}
        />
      ) : null}
      {error && open !== "request" ? (
        <Alert type="error" showIcon role="alert" message={error} />
      ) : null}
    </section>
  );
}
