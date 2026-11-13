import { Alert, Button } from "antd";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../../shared/api/errors";
import type { LetterIntakeSuggestion } from "../../../shared/api/generated/model";
import {
  suggestLetterFromFile,
  useGetDocflowSettings,
  useListEdsDealOptions,
} from "../../../shared/api/generated/platform-bff";
import type { Attachment, DealChoice } from "../new/formModel";

const REASONS = new Set([
  "scan_recognition_disabled",
  "file_too_large",
  "ai_unavailable",
  "ai_budget_exceeded",
  "nothing_recognized",
]);

function errorKey(error: unknown): string {
  if (error instanceof ApiError) {
    const reason = error.details["reason"];
    if (typeof reason === "string" && REASONS.has(reason)) return reason;
    if (error.status === 422) return "unsupported_file";
  }
  return "DEFAULT";
}

/** Возможная связь с проектом: код ищет заявку по ИНН, затем по названию корреспондента (не модель). */
function DealSuggestion({
  inn,
  name,
  onLink,
}: {
  inn: string;
  name: string;
  onLink: (choice: DealChoice) => void;
}) {
  const { t } = useTranslation("letters");
  const byInn = useListEdsDealOptions(
    { q: inn },
    { query: { staleTime: 30_000, enabled: inn !== "" } },
  );
  const innEmpty = inn === "" || (byInn.isSuccess && byInn.data.items.length === 0);
  const byName = useListEdsDealOptions(
    { q: name },
    { query: { staleTime: 30_000, enabled: innEmpty && name !== "" } },
  );
  const first = byInn.data?.items[0] ?? (innEmpty ? byName.data?.items[0] : undefined);
  if (!first) return null;
  const label = [first.number, first.title, first.company].filter(Boolean).join(" · ");
  return (
    <Alert
      type="info"
      showIcon
      message={t("register.ai.deal", { label })}
      action={
        <Button
          size="small"
          onClick={() => {
            onLink({ erp_deal_id: first.erp_deal_id, label });
          }}
        >
          {t("register.ai.link")}
        </Button>
      }
    />
  );
}

/**
 * «Заполнить из файла» (EDS-REG; стандарт ИИ-помощника — исследование 2026-11-02 §4.1). Форма начинается с загрузки (ВХ,
 * правило владельца 2026-11-11): загрузка первого файла сама запускает распознавание — это и есть нажатие кнопки (юрист
 * 2026-11-11), кнопка остаётся для повтора. Предложенные поля помечены «Предложено ИИ», заполняются только пустые; человек
 * проверяет и регистрирует. Помощник не настроен или выключен администратором — кнопки и распознавания нет.
 */
export function AiFillBar({
  attachments,
  applied,
  linkQuery,
  onSuggestion,
  onRevert,
  onLinkDeal,
}: {
  attachments: readonly Attachment[];
  /** Сколько полей заполнено из файла; 0 — предложения нет */
  applied: number;
  /** ИНН и название корреспондента для поиска связи с проектом; `null` — не искать */
  linkQuery: { inn: string; name: string } | null;
  onSuggestion: (suggestion: LetterIntakeSuggestion) => void;
  onRevert: () => void;
  onLinkDeal: (choice: DealChoice) => void;
}) {
  const { t } = useTranslation("letters");
  const settings = useGetDocflowSettings({ query: { staleTime: 60_000 } });
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const file = attachments.find((item) => item.status === "done" && item.id);
  const available = Boolean(settings.data?.ai_available);

  const fill = async () => {
    if (!file?.id) return;
    setPending(true);
    setFailure(null);
    try {
      onSuggestion(await suggestLetterFromFile({ file_id: file.id }));
    } catch (error) {
      setFailure(t(`register.ai.errors.${errorKey(error)}`));
    } finally {
      setPending(false);
    }
  };

  // Первый загруженный файл распознаётся сам, один раз на файл; уже заполненная форма (из почты, предложение есть) — нет.
  const tried = useRef<string | null>(null);
  const fileId = file?.id ?? null;
  useEffect(() => {
    if (!available || !fileId || applied > 0 || tried.current === fileId) return;
    tried.current = fileId;
    void fill();
    // fill — свежая функция на каждой отрисовке; запуск — по новому файлу
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [available, fileId]);

  if (!available || !settings.data) return null;

  return (
    <div className="pf-reg-ai" role="group" aria-label={t("register.ai.group")}>
      <div className="pf-reg-ai-row">
        <Button
          loading={pending}
          disabled={!file}
          aria-describedby="reg-ai-hint"
          onClick={() => {
            void fill();
          }}
        >
          {t("register.ai.fill")}
        </Button>
        <span className="pf-hint" id="reg-ai-hint">
          {!file
            ? t("register.ai.needFile")
            : settings.data.recognize_scans && settings.data.pii_policy === "business"
              ? t("register.ai.hintScans")
              : t("register.ai.hintText")}
        </span>
      </div>
      {pending ? (
        <p className="pf-hint" role="status">
          {t("register.ai.reading")}
        </p>
      ) : null}
      {failure ? <Alert type="warning" showIcon role="alert" message={failure} /> : null}
      {applied > 0 ? (
        <Alert
          type="info"
          showIcon
          role="status"
          message={t("register.ai.applied", { count: applied })}
          action={
            <Button size="small" onClick={onRevert}>
              {t("register.ai.revert")}
            </Button>
          }
        />
      ) : null}
      {applied > 0 && linkQuery ? (
        <DealSuggestion inn={linkQuery.inn} name={linkQuery.name} onLink={onLinkDeal} />
      ) : null}
    </div>
  );
}
