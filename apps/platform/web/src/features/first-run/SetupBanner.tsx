import { App, Button } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router";

import { canEdit } from "../../app/access";
import { useAuth } from "../../app/auth/useAuth";
import { WIZARD_PATH, needsSetup, nextStep } from "../../entities/setup/steps";
import { LinkButton } from "../../shared/ui/LinkButton";
import { hideBanner, isBannerHidden } from "./hidden";
import { useSetupChecklist } from "./useSetupChecklist";

import "./first-run.css";

/**
 * Баннер «Настройка Платформы» над основным окном (SPEC-v3 §7.6): сколько из пяти шагов сделано, что дальше, одна ссылка
 * в мастер и «Скрыть» (запоминается в браузере). Только администратору (`admin` — полный): чек-лист отдаёт BFF с этим
 * правом, а шаги ведут на экраны, которые меняет администратор; директор баннера не видит. Пока шагов не осталось, а
 * компания создана, баннера нет. На самой странице мастера он не нужен.
 */
export function SetupBanner() {
  const { t } = useTranslation("modules");
  const { message } = App.useApp();
  const { me } = useAuth();
  const location = useLocation();
  const allowed = canEdit(me, "admin");
  const checklist = useSetupChecklist(allowed);
  const [hidden, setHidden] = useState(() => isBannerHidden(me.id));

  if (!allowed || hidden || location.pathname === WIZARD_PATH) return null;
  const data = checklist.data;
  if (!data || !needsSetup(data)) return null;

  const next = nextStep(data);
  return (
    <section className="pf-setup-banner" aria-label={t("admin.setup.banner.label")}>
      <div className="pf-setup-banner-text">
        <p className="pf-setup-banner-title">
          {t("admin.setup.banner.title", { done: data.done, total: data.total })}
        </p>
        <span className="pf-hint">
          {data.company?.required ? `${t("admin.setup.banner.company")} ` : ""}
          {next
            ? t("admin.setup.banner.next", { step: t(`admin.setup.steps.${next.key}.title`) })
            : ""}
        </span>
      </div>
      <div className="pf-setup-banner-actions">
        <LinkButton type="primary" to={WIZARD_PATH}>
          {t("admin.setup.banner.open")}
        </LinkButton>
        <Button
          aria-label={t("admin.setup.banner.hideLabel")}
          onClick={() => {
            hideBanner(me.id);
            setHidden(true);
            void message.info(t("admin.setup.banner.hidden"));
          }}
        >
          {t("admin.setup.banner.hide")}
        </Button>
      </div>
    </section>
  );
}
