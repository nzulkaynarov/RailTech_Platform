import { Alert, Button } from "antd";
import { useId, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { useAuth } from "../../app/auth/useAuth";
import type { ServiceVersion } from "../../shared/api/generated/model";
import { useFormat } from "../../shared/lib/useFormat";
import { StatusTag } from "../../shared/ui/StatusTag";
import { releaseText, supportText, useAbout } from "./release";

import "../help/help.css";

function ServiceRow({ service }: { service: ServiceVersion }) {
  const { t } = useTranslation("help");
  return (
    <li className="pf-about-row">
      <span style={{ fontWeight: 500 }}>{t(`about.service.${service.key}`)}</span>
      <StatusTag kind="service" status={service.status}>
        {t(`about.status.${service.status}`)}
      </StatusTag>
      <span className="pf-hint">
        {service.version
          ? t("about.serviceVersion", { version: service.version })
          : t("about.noVersion")}
      </span>
    </li>
  );
}

/** Сервисы BFF, CRM, ERP, EDS: состояние словом и версия, если сервис её сообщает (W-REL). */
export function ServiceVersions({ services }: { services: readonly ServiceVersion[] }) {
  const { t } = useTranslation("help");
  return (
    <ul className="pf-help-list pf-about-services" aria-label={t("about.services")}>
      {services.map((service) => (
        <ServiceRow key={service.key} service={service} />
      ))}
    </ul>
  );
}

/**
 * «Помощь → О системе» (W-REL): версия Платформы по дате выкладки и sha, дата обновления, сервисы и «Скопировать данные
 * для поддержки» — версия, роль, язык, браузер, экран и время, без персональных данных. Текст виден до копирования:
 * сотрудник знает, что отправит, и может скопировать руками, если браузер не дал.
 */
export function AboutPanel() {
  const { t } = useTranslation("help");
  const { me } = useAuth();
  const { date } = useFormat();
  const about = useAbout();
  const supportId = useId();
  const [copy, setCopy] = useState<"idle" | "done" | "failed">("idle");
  const release = about.data?.release;
  const support = useMemo(
    () =>
      supportText(t, {
        me,
        release,
        userAgent: navigator.userAgent,
        screen: { width: window.innerWidth, height: window.innerHeight },
        now: new Date(),
      }),
    [t, me, release],
  );

  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(support);
      setCopy("done");
    } catch {
      setCopy("failed");
    }
  };

  return (
    <div className="pf-help-block">
      <h2 style={{ margin: 0, fontSize: 16, lineHeight: "24px", fontWeight: 600 }}>
        {t("about.title")}
      </h2>
      {about.isError ? (
        <Alert type="error" showIcon role="alert" message={t("about.error")} />
      ) : !about.data ? (
        <p role="status" style={{ margin: 0 }}>
          {t("about.loading")}
        </p>
      ) : (
        <>
          <div>
            <p style={{ margin: 0, fontSize: 16, fontWeight: 600 }} data-testid="release">
              {releaseText(t, release)}
            </p>
            {release?.released_at ? (
              <p className="pf-hint" style={{ margin: 0 }}>
                {t("about.releasedAt", { date: date(release.released_at) })}
              </p>
            ) : release?.built_at ? (
              <p className="pf-hint" style={{ margin: 0 }}>
                {t("about.builtAt", { date: date(release.built_at) })}
              </p>
            ) : null}
          </div>
          <div>
            <h3 style={{ margin: "0 0 4px", fontSize: 14, lineHeight: "22px", fontWeight: 600 }}>
              {t("about.services")}
            </h3>
            <ServiceVersions services={about.data.services} />
          </div>
        </>
      )}
      <div>
        <h3
          id={supportId}
          style={{ margin: "0 0 4px", fontSize: 14, lineHeight: "22px", fontWeight: 600 }}
        >
          {t("about.supportLabel")}
        </h3>
        <p className="pf-hint" style={{ margin: "0 0 8px" }}>
          {t("about.supportHint")}
        </p>
        <pre className="pf-about-support" aria-labelledby={supportId} tabIndex={0}>
          {support}
        </pre>
        <Button onClick={() => void onCopy()}>{t("about.copy")}</Button>
        <div aria-live="polite" style={{ marginTop: 8 }}>
          {copy === "done" ? <p style={{ margin: 0 }}>{t("about.copied")}</p> : null}
          {copy === "failed" ? <p style={{ margin: 0 }}>{t("about.copyFailed")}</p> : null}
        </div>
      </div>
    </div>
  );
}
