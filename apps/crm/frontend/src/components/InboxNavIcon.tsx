import { InboxOutlined } from "@ant-design/icons";
import { Badge } from "antd";

import { useInbox } from "../api/queries";
import { openHandoffCount } from "../domain/sla";
import { t } from "../i18n/ru";

/**
 * Иконка пункта «Входящие» со счётчиком открытых передач (дизайн-аудит 2026-10-11, P-23):
 * менеджер в другом разделе видит, что пришла передача. Данные — тот же запрос инбокса,
 * его перечитывает SSE (`useEventStream`), своего опроса нет. Рендерится только при
 * доступе к разделу (`CanAccess` в меню Refine). `className` проставляет меню antd.
 */
export function InboxNavIcon({ className }: { className?: string }) {
  const { data } = useInbox();
  const count = openHandoffCount(data);
  return (
    <span className={className}>
      <Badge count={count} size="small" offset={[4, -2]} aria-hidden>
        <InboxOutlined />
      </Badge>
      {count ? (
        <span className="sr-only">{t.inbox.navCount.replace("{count}", String(count))}</span>
      ) : null}
    </span>
  );
}
