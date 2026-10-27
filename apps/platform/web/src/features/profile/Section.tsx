import { type ReactNode, useId } from "react";

import "./profile.css";

/** Блок страницы /me: карточка с заголовком второго уровня и пояснением. */
export function Section({
  title,
  lead,
  children,
  testId,
}: {
  title: string;
  lead?: ReactNode;
  children: ReactNode;
  testId?: string;
}) {
  const id = useId();
  return (
    <section className="pf-card pf-profile-section" aria-labelledby={id} data-testid={testId}>
      <div className="pf-card-head">
        <h2 id={id} className="pf-card-title">
          {title}
        </h2>
      </div>
      <div className="pf-profile-body">
        {lead ? (
          <p className="pf-hint" style={{ margin: "0 0 12px" }}>
            {lead}
          </p>
        ) : null}
        {children}
      </div>
    </section>
  );
}
