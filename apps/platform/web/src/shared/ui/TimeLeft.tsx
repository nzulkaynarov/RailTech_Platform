import { useTranslation } from "react-i18next";

import { daysUntil } from "../lib/format";
import "./ui.css";

/**
 * «Осталось N дн.» рядом со сроком (план §3f РЕФ-3): срок читается без подсчёта. Только у открытого срока сегодня или в
 * будущем — просрочку говорит статус. Два дня и меньше — цветом предупреждения.
 */
export function TimeLeft({ date, now }: { date?: string | null; now?: number }) {
  const { t } = useTranslation("ui");
  if (!date) return null;
  const days = daysUntil(date, now);
  if (Number.isNaN(days) || days < 0) return null;
  return (
    <span className={days <= 2 ? "pf-time-left pf-time-left--soon" : "pf-time-left"}>
      {days === 0 ? t("timeLeft.today") : t("timeLeft.days", { count: days })}
    </span>
  );
}
