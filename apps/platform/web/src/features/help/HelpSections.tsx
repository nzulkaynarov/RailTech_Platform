import { useTranslation } from "react-i18next";

import { useAuth } from "../../app/auth/useAuth";
import { START_KINDS, type StartKind, rolesText, startKindsOf, useStartSteps } from "./startKinds";

import "./help.css";

function KindBlock({ kind, role }: { kind: StartKind; role?: string }) {
  const { t } = useTranslation("help");
  const steps = useStartSteps(kind);
  return (
    <section aria-labelledby={`start-${kind}`} className="pf-help-block">
      <h2 id={`start-${kind}`} style={{ margin: 0, fontSize: 16, lineHeight: "24px" }}>
        {role ? t("start.yours", { role }) : t(`start.kinds.${kind}.title`)}
      </h2>
      <ol style={{ margin: 0, paddingLeft: 20 }}>
        {steps.map((step) => (
          <li key={step} style={{ marginBottom: 4 }}>
            {step}
          </li>
        ))}
      </ol>
    </section>
  );
}

/** «С чего начать»: 3–5 шагов для видов работы сотрудника (по разделам каталога), затем — для остальных ролей. */
export function StartGuide() {
  const { t } = useTranslation("help");
  const { me } = useAuth();
  const mine = startKindsOf(me);
  const role = rolesText(me);
  const others = START_KINDS.filter((kind) => !mine.includes(kind));
  return (
    <div className="pf-help-block" style={{ gap: 24 }}>
      <p style={{ margin: 0 }}>{t("start.intro")}</p>
      {mine.map((kind, index) => (
        <KindBlock key={kind} kind={kind} {...(index === 0 ? { role } : {})} />
      ))}
      {others.length > 0 ? (
        <div className="pf-help-block">
          <h2 style={{ margin: 0, fontSize: 16, lineHeight: "24px" }}>{t("start.others")}</h2>
          {others.map((kind) => (
            <KindBlock key={kind} kind={kind} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

interface PathStep {
  title: string;
  who: string;
  text: string;
}

/** «Путь заявки»: семь шагов SPEC-v3 §2.3, у каждого владелец. */
export function PathGuide() {
  const { t } = useTranslation("help");
  const steps = t("path.steps", { returnObjects: true }) as PathStep[];
  return (
    <div className="pf-help-block">
      <p style={{ margin: 0 }}>{t("path.intro")}</p>
      <ol className="pf-help-steps">
        {steps.map((step) => (
          <li key={step.title}>
            <div style={{ fontWeight: 600 }}>{step.title}</div>
            <div className="pf-hint">{t("path.owner", { who: step.who })}</div>
            <div>{step.text}</div>
          </li>
        ))}
      </ol>
      <p className="pf-hint" style={{ margin: 0 }}>
        {t("path.lost")}
      </p>
    </div>
  );
}

/** «Словарь»: ВХ, ЗВ, КП, СЗ и остальные слова интерфейса. */
export function Glossary() {
  const { t } = useTranslation("help");
  const items = t("glossary.items", { returnObjects: true }) as { term: string; text: string }[];
  return (
    <div className="pf-help-block">
      <p style={{ margin: 0 }}>{t("glossary.intro")}</p>
      <dl style={{ margin: 0 }}>
        {items.map((item) => (
          <div key={item.term} style={{ padding: "8px 0", borderBottom: "1px solid #f0f0f0" }}>
            <dt className="pf-help-term">{item.term}</dt>
            <dd style={{ margin: 0 }}>{item.text}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** «Горячие клавиши»: те, что действуют сейчас. */
export function Hotkeys() {
  const { t } = useTranslation("help");
  const items = t("keys.items", { returnObjects: true }) as { keys: string; text: string }[];
  return (
    <div className="pf-help-block">
      <p style={{ margin: 0 }}>{t("keys.intro")}</p>
      <dl style={{ margin: 0 }}>
        {items.map((item) => (
          <div
            key={item.keys}
            style={{
              padding: "8px 0",
              borderBottom: "1px solid #f0f0f0",
              display: "flex",
              gap: 12,
            }}
          >
            <dt style={{ flex: "0 0 150px" }}>
              <kbd className="pf-help-key">{item.keys}</kbd>
            </dt>
            <dd style={{ margin: 0 }}>{item.text}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** «Что нового»: изменения Платформы для сотрудников. */
export function News() {
  const { t } = useTranslation("help");
  const items = t("news.items", { returnObjects: true }) as {
    date: string;
    title: string;
    text: string;
  }[];
  return (
    <div className="pf-help-block">
      <p style={{ margin: 0 }}>{t("news.intro")}</p>
      <ul className="pf-help-list">
        {items.map((item) => (
          <li key={item.title}>
            <div className="pf-hint">{item.date}</div>
            <div style={{ fontWeight: 600 }}>{item.title}</div>
            <div>{item.text}</div>
          </li>
        ))}
      </ul>
    </div>
  );
}
