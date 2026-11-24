import { theme } from "antd";
import { type ReactNode, useCallback, useContext } from "react";
import { useTranslation } from "react-i18next";

import { LockIcon } from "./icons";
import { PageTabsSlotContext } from "./pageTabsSlot";
import { StatusTag } from "./StatusTag";

/**
 * Единственная плашка «Только просмотр»: у страницы, которую сотрудник видит, но не правит. Один компонент на все
 * экраны — вместо строки под заголовком и второй плашки в карточке.
 */
export function ReadOnlyTag() {
  const { t } = useTranslation("ui");
  return (
    <StatusTag tone="default">
      <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
        <LockIcon size={12} />
        {t("readOnly")}
      </span>
    </StatusTag>
  );
}

/**
 * Заголовок страницы основного окна: 20/600 (строка 28) и подзаголовок `#595959` (docs/architecture/platform-frontend.md §4).
 * Подзаголовок — короткая строка состояния («Демо Менеджеров», «версия 2»), не пересказ того, что делает экран.
 * `readOnly` — одна плашка «Только просмотр» справа. Под заголовком — место вкладок раздела (`pageTabsSlot`).
 */
export function PageHeader({
  title,
  subtitle,
  extra,
  readOnly = false,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  extra?: ReactNode;
  readOnly?: boolean;
}) {
  const { token } = theme.useToken();
  const slot = useContext(PageTabsSlotContext);
  const register = slot?.register;
  const place = useCallback(
    (element: HTMLDivElement | null) => {
      register?.(element);
    },
    [register],
  );
  return (
    <>
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 16,
          flexWrap: "wrap",
        }}
      >
        <div style={{ minWidth: 0 }}>
          <h1 style={{ margin: 0, fontSize: 20, lineHeight: "28px", fontWeight: 600 }}>{title}</h1>
          {subtitle ? <div style={{ color: token.colorTextSecondary }}>{subtitle}</div> : null}
        </div>
        {extra || readOnly ? (
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {readOnly ? <ReadOnlyTag /> : null}
            {extra}
          </div>
        ) : null}
      </div>
      {slot ? <div ref={place} style={{ display: "contents" }} /> : null}
    </>
  );
}
