import { Button } from "antd";
import { useId } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router";

import { useViewport } from "../../app/shell/useViewport";
import { CHANGELOG, entryDate } from "./changelog";
import { useWhatsNew } from "./whatsNew";

import "./help.css";

/**
 * «Платформа обновлена — что нового» (W-REL): ненавязчивое окно в углу при первом входе после выкладки с новой записью.
 * Не модальное — работать можно сразу; «Закрыть» и «Что нового» снимают окно навсегда (отметка `shown` в CRM), отметка
 * «Новое» у «?» остаётся, пока сотрудник не откроет «Что нового». На первом входе окно ждёт, пока закроют приветствие.
 * Фокус окно не забирает; текст — `role="status"`, скринридер его объявит.
 */
export function WhatsNewNotice() {
  const { t, i18n } = useTranslation("help");
  const navigate = useNavigate();
  const location = useLocation();
  const { mobile } = useViewport();
  const { latest, noticeDue, mark } = useWhatsNew();
  const titleId = useId();
  const textId = useId();
  const entry = CHANGELOG[0];
  const onNews = location.pathname.startsWith("/help/news");
  const visible = noticeDue && !onNews && entry !== undefined && latest !== undefined;

  if (!visible) return null;

  const close = () => {
    mark({ shown: latest });
  };
  const open = () => {
    mark({ read: latest });
    void navigate("/help/news");
  };

  return (
    <div
      role="region"
      aria-labelledby={titleId}
      aria-describedby={textId}
      className="pf-whats-new"
      style={mobile ? { left: 8, right: 8, bottom: 72 } : { right: 24, bottom: 24, width: 360 }}
    >
      <h2 id={titleId} style={{ margin: 0, fontSize: 16, lineHeight: "24px", fontWeight: 600 }}>
        {t("whatsNew.title")}
      </h2>
      <p id={textId} role="status" style={{ margin: "4px 0 12px" }}>
        {t("whatsNew.text", { date: entryDate(entry.date, i18n.language), title: entry.title })}
      </p>
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <Button onClick={close}>{t("whatsNew.close")}</Button>
        <Button type="primary" onClick={open}>
          {t("whatsNew.open")}
        </Button>
      </div>
    </div>
  );
}
