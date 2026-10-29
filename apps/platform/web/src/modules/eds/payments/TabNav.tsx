import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import type { PaymentCounts } from "../../../shared/api/generated/model";
import { withParams } from "../inbox/api";
import { type ShowTab, TABS } from "./model";

/**
 * Вкладки «Счетов и оплат» (SPEC-v3 §7.3): навигация ссылками, а не `role=tab` — адрес хранит выбранную вкладку, текущая
 * отмечена `aria-current`. Число — счетов на вкладке (вкладки не пересекаются); просроченные подсвечены словом и цветом.
 */
export function TabNav({
  active,
  counts,
  memos,
}: {
  active: ShowTab;
  counts: PaymentCounts | undefined;
  memos: number | null | undefined;
}) {
  const { t } = useTranslation("payments");
  const [params] = useSearchParams();
  const number = (tab: ShowTab): number | null | undefined =>
    tab === "memos" ? memos : tab === "all" ? undefined : counts?.[tab];
  return (
    <nav aria-label={t("list.tabsLabel")}>
      <ul className="pf-pay-tabs">
        {TABS.map((tab) => {
          const count = number(tab);
          return (
            <li key={tab}>
              <Link
                className="pf-focusable pf-pay-tab"
                replace
                aria-current={tab === active ? "page" : undefined}
                to={withParams(params, {
                  show: tab,
                  viewTab: tab,
                  payment: null,
                  memo: null,
                  sheet: null,
                  panel: null,
                  tab: null,
                })}
              >
                {t(`list.tabs.${tab}`)}
                {typeof count === "number" ? (
                  <span className="pf-pay-count" data-alert={tab === "overdue" && count > 0}>
                    {count}
                  </span>
                ) : null}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
