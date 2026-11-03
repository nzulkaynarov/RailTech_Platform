import { Alert, Skeleton } from "antd";
import { useTranslation } from "react-i18next";

import { useGetDocflowSettings } from "../../../shared/api/generated/platform-bff";
import { TabHeader } from "../company/common";

/**
 * Настройки · Документооборот · ИИ-помощник (EDS-REG): «Заполнить из файла» в регистрации входящих. PDF с текстом
 * помощник читает всегда (персональные данные скрывает код до модели). Сканы и фото — серверная настройка
 * `recognize_scans` (по умолчанию выключена); переключателя здесь нет, пока владелец и юрист не решат, можно ли отправлять
 * сканы писем в модель (docs/QUESTIONS.md, Q-EDSREG-1). Экран показывает состояние словами.
 */
export function AiTab() {
  const { t } = useTranslation("letters");
  const settings = useGetDocflowSettings();

  return (
    <div className="pf-co-body">
      <TabHeader title={t("settings.ai.title")} hint={t("settings.ai.hint")} />
      {settings.isPending ? <Skeleton active paragraph={{ rows: 2 }} title={false} /> : null}
      {settings.isError ? (
        <Alert type="error" showIcon role="alert" message={t("settings.dict.errors.load")} />
      ) : null}
      {settings.data ? (
        <>
          {settings.data.ai_available ? null : (
            <Alert type="warning" showIcon message={t("settings.ai.off")} />
          )}
          <p className="pf-hint" style={{ margin: 0 }}>
            {t("settings.ai.text")}
          </p>
          <p className="pf-hint" style={{ margin: 0 }}>
            {settings.data.recognize_scans ? t("settings.ai.scansOn") : t("settings.ai.scansLater")}
          </p>
        </>
      ) : null}
    </div>
  );
}
