import { CheckOutlined, ExclamationOutlined } from "@ant-design/icons";
import { Button } from "antd";
import { type ReactNode, useId } from "react";
import { useTranslation } from "react-i18next";

import "./step-sections.css";

export interface StepSection {
  key: string;
  title: string;
  /** Строка итога свёрнутой секции: что уже заполнено */
  summary?: ReactNode;
  /** Секция заполнена — у номера галочка */
  complete?: boolean;
  /** В секции ошибка — отметка «нужно исправить» */
  invalid?: boolean;
  content: ReactNode;
  /** Кнопки внизу секции рядом с «Далее» (например, «Сохранить черновик») */
  footer?: ReactNode;
}

export interface StepSectionsProps {
  sections: readonly StepSection[];
  active: string;
  onActiveChange: (key: string) => void;
  /**
   * Уровень заголовков секций: 2 — на странице документа, 3 — внутри вкладки с заголовком `h2` (настройки), 4 — в боковом
   * окне под заголовком формы `h3`
   */
  headingLevel?: 2 | 3 | 4;
}

/**
 * Секции по шагам для длинных форм (platform-frontend.md §4.1a): пронумерованы, открыта одна; свёрнутая показывает строку
 * итога; вернуться можно к любой. Содержимое скрытых секций остаётся в разметке (`hidden`), поэтому набранное не теряется.
 */
export function StepSections({
  sections,
  active,
  onActiveChange,
  headingLevel = 2,
}: StepSectionsProps) {
  const { t } = useTranslation("ui");
  const Heading = headingLevel === 4 ? "h4" : headingLevel === 3 ? "h3" : "h2";
  const base = useId();
  return (
    <ol className="pf-fsteps">
      {sections.map((section, index) => {
        const open = section.key === active;
        const next = sections[index + 1];
        const headId = `${base}-${section.key}-head`;
        const bodyId = `${base}-${section.key}-body`;
        return (
          <li
            key={section.key}
            className="pf-fstep"
            data-open={open || undefined}
            data-invalid={section.invalid || undefined}
          >
            <Heading className="pf-fstep-heading">
              <button
                type="button"
                id={headId}
                className="pf-fstep-head pf-focusable"
                aria-expanded={open}
                aria-controls={bodyId}
                onClick={() => {
                  onActiveChange(section.key);
                }}
              >
                <span className="pf-fstep-badge" aria-hidden="true">
                  {section.invalid ? (
                    <ExclamationOutlined />
                  ) : section.complete && !open ? (
                    <CheckOutlined />
                  ) : (
                    index + 1
                  )}
                </span>
                <span className="pf-fstep-text">
                  <span className="pf-fstep-title">{section.title}</span>
                  {!open && section.summary ? (
                    <span className="pf-fstep-summary">{section.summary}</span>
                  ) : null}
                  {section.invalid ? (
                    <span className="pf-fstep-error">{t("formSteps.invalid")}</span>
                  ) : null}
                </span>
                {!open ? <span className="pf-fstep-edit">{t("formSteps.edit")}</span> : null}
              </button>
            </Heading>
            <div
              id={bodyId}
              role="region"
              aria-labelledby={headId}
              className="pf-fstep-body"
              hidden={!open}
            >
              {section.content}
              {next || section.footer ? (
                <div className="pf-fstep-footer">
                  {next ? (
                    <Button
                      type="primary"
                      onClick={() => {
                        onActiveChange(next.key);
                      }}
                    >
                      {t("formSteps.next", { title: next.title })}
                    </Button>
                  ) : null}
                  {section.footer}
                </div>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
