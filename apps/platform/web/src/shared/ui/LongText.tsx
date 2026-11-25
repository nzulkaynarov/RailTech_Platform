import { Button } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

/** Длиннее этого (или больше строк) — текст сворачивается до нескольких строк с «Показать полностью». */
const LIMIT_CHARS = 280;
const LIMIT_LINES = 5;

/** Нужна ли свёртка: письмо или обращение на сорок строк не должно вытеснять с панели остальное (СЦ-7, N5). */
function isLong(text: string): boolean {
  return text.length > LIMIT_CHARS || text.split("\n").length > LIMIT_LINES;
}

/**
 * Длинный текст пользователя (сообщение, запрос): первые строки и «Показать полностью»; короткий — как есть.
 * Один компонент для панелей и карточек, чтобы письмо не печаталось целиком дважды.
 */
export function LongText({ text, className }: { text: string; className?: string }) {
  const { t } = useTranslation("ui");
  const [expanded, setExpanded] = useState(false);
  const id = useId();
  const long = isLong(text);
  return (
    <>
      <span
        id={id}
        className={["pf-long-text", className].filter(Boolean).join(" ")}
        data-clamped={long && !expanded}
      >
        {text}
      </span>
      {long ? (
        <Button
          type="link"
          size="small"
          className="pf-long-text-toggle"
          aria-expanded={expanded}
          aria-controls={id}
          onClick={() => {
            setExpanded((value) => !value);
          }}
        >
          {t(expanded ? "longText.less" : "longText.more")}
        </Button>
      ) : null}
    </>
  );
}
