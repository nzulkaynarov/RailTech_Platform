import { App, Button } from "antd";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router";

import { canEdit } from "../../app/access";
import { useAuth } from "../../app/auth/useAuth";
import { WIZARD_PATH, bankDetailsMissing, visibleTitleKey } from "../../entities/setup/steps";
import { LinkButton } from "../../shared/ui/LinkButton";
import { hideBanner, useBannerHidden } from "./hidden";
import { useSetupProgress } from "./useSetupProgress";

import "./first-run.css";

/**
 * Баннер «Настройка Платформы» над основным окном (SPEC-v3 §7.6): сколько из пяти шагов сделано, что дальше, одна ссылка
 * в мастер и «Скрыть до завтра» (W15-H4; запоминается в браузере, вернуть — в мастере). Только администратору (`admin` — полный): чек-лист отдаёт BFF с этим
 * правом, а шаги ведут на экраны, которые меняет администратор; директор баннера не видит. Пока шагов не осталось, а
 * компания создана, баннера нет. На самой странице мастера он не нужен.
 */
export function SetupBanner() {
  const { t } = useTranslation("modules");
  const { message } = App.useApp();
  const { me } = useAuth();
  const location = useLocation();
  const allowed = canEdit(me, "admin");
  const { checklist, done, total, next } = useSetupProgress(allowed);
  const hidden = useBannerHidden(me.id);

  // На мастере и на индексе Настроек (там свой чек-лист «Первый запуск», SET-IA) баннер не нужен.
  if (!allowed || hidden || location.pathname === WIZARD_PATH || location.pathname === "/admin")
    return null;
  const data = checklist.data;
  // Баннер — пока есть несделанный видимый шаг (СЦ-3): тот же список, что считает «готово N из M» и «Дальше».
  if (!data || !next) return null;

  return (
    <section className="pf-setup-banner" aria-label={t("admin.setup.banner.label")}>
      <div className="pf-setup-banner-text">
        <p className="pf-setup-banner-title">{t("admin.setup.banner.title", { done, total })}</p>
        <span className="pf-hint">
          {data.company?.required ? `${t("admin.setup.banner.company")} ` : ""}
          {bankDetailsMissing(data) ? `${t("admin.setup.banner.bank")} ` : ""}
          {t("admin.setup.banner.next", { step: t(visibleTitleKey(next.key)) })}
        </span>
      </div>
      <div className="pf-setup-banner-actions">
        <LinkButton type="primary" to={next.to}>
          {t("admin.setup.banner.open")}
        </LinkButton>
        <Button
          aria-label={t("admin.setup.banner.hideLabel")}
          onClick={() => {
            hideBanner(me.id);
            void message.info(t("admin.setup.banner.hidden"));
          }}
        >
          {t("admin.setup.banner.hide")}
        </Button>
      </div>
    </section>
  );
}
