import { Alert, Button } from "antd";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { Employee } from "../../shared/api/generated/model";

import "../first-run/first-run.css";

export interface TemporaryPasswordCardProps {
  employee: Employee;
  /** Пароль из ответа BFF: живёт только в состоянии этого окна и пропадает после «Готово» */
  password: string;
  onDone: () => void;
}

/**
 * Одноразовый временный пароль (SPEC-v3 §7.6): показывается администратору один раз, с предупреждением и кнопкой
 * «Копировать». Это единственное место, где пароль есть на экране; в адрес, историю и кэш запросов он не попадает.
 * Пароль виден намеренно (его надо прочитать и передать), поле только для чтения.
 */
export function TemporaryPasswordCard({ employee, password, onDone }: TemporaryPasswordCardProps) {
  const { t } = useTranslation("modules");
  const labelId = useId();
  const input = useRef<HTMLInputElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const [copy, setCopy] = useState<"idle" | "done" | "failed">("idle");

  useEffect(() => {
    heading.current?.focus();
  }, []);

  const copyPassword = async () => {
    try {
      await navigator.clipboard.writeText(password);
      setCopy("done");
    } catch {
      // Буфер недоступен (http, запрет браузера): выделяем пароль, чтобы скопировать вручную.
      input.current?.select();
      setCopy("failed");
    }
  };

  return (
    <section className="pf-panel-stack" aria-label={t("admin.org.password.cardLabel")}>
      <h3
        ref={heading}
        tabIndex={-1}
        style={{ margin: 0, fontSize: 16, lineHeight: "24px", fontWeight: 600, outline: "none" }}
      >
        {t("admin.org.password.title")}
      </h3>
      <p className="pf-hint" style={{ margin: 0 }}>
        {t("admin.org.password.lead", { name: employee.name, email: employee.email })}
      </p>
      <Alert type="warning" showIcon message={t("admin.org.password.warning")} />
      <div>
        <label
          id={labelId}
          htmlFor={`${labelId}-input`}
          style={{ display: "block", fontWeight: 600 }}
        >
          {t("admin.org.password.label")}
        </label>
        <div className="pf-password-box" style={{ marginTop: 4 }}>
          <input
            id={`${labelId}-input`}
            ref={input}
            className="ant-input"
            readOnly
            value={password}
            autoComplete="off"
            spellCheck={false}
            onFocus={(event) => {
              event.currentTarget.select();
            }}
          />
          <Button
            onClick={() => {
              void copyPassword();
            }}
          >
            {t("admin.org.password.copy")}
          </Button>
        </div>
        <p className="pf-hint" role="status" style={{ margin: "4px 0 0", minHeight: 20 }}>
          {copy === "done" ? t("admin.org.password.copied") : null}
          {copy === "failed" ? t("admin.org.password.copyFailed") : null}
        </p>
      </div>
      <p className="pf-hint" style={{ margin: 0 }}>
        {t("admin.org.password.howTo")}
      </p>
      <Button type="primary" block onClick={onDone}>
        {t("admin.org.password.done")}
      </Button>
    </section>
  );
}
