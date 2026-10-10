import { MenuOutlined } from "@ant-design/icons";
import { useThemedLayoutContext } from "@refinedev/antd";
import { useGetIdentity } from "@refinedev/core";
import { Badge, Button, Grid, Layout, Space, theme, Typography } from "antd";

import { ModeSwitch } from "../components/ModeSwitch";
import { useEventStream } from "../hooks/useEventStream";
import { t } from "../i18n/ru";

/** Состояние SSE-соединения текстом, а не только цветом точки (WCAG 1.4.1, 4.1.3). */
export function ConnectionStatus({ live, compact = false }: { live: boolean; compact?: boolean }) {
  const text = live ? t.common.live : t.common.offline;
  return (
    <span role="status" title={live ? t.common.liveHint : t.common.offlineHint}>
      <Badge status={live ? "success" : "warning"} text={compact ? null : text} />
      {compact ? <span className="sr-only">{text}</span> : null}
    </span>
  );
}

/**
 * Шапка. На экранах уже `lg` меню Refine — выдвижная панель; кнопка открытия здесь,
 * а не плавающая поверх заголовка страницы (дизайн-аудит 2026-10-11, отчёт 2).
 */
export function Header() {
  const { data: identity } = useGetIdentity<{ name: string }>();
  const live = useEventStream(Boolean(identity));
  const { token } = theme.useToken();
  const screens = Grid.useBreakpoint();
  const { setMobileSiderOpen } = useThemedLayoutContext();
  // Та же граница, что у ThemedSider: меню-панель, пока брейкпоинт `lg` не достигнут.
  const drawerMenu = screens.lg === false;
  // На телефоне в шапке только самое нужное: статус точкой, переключатель режима; имя — в профиле.
  const phone = screens.sm === false;
  return (
    <Layout.Header
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        gap: token.marginSM,
        padding: `0 ${String(token.padding)}px`,
        background: token.colorBgContainer,
      }}
    >
      {drawerMenu ? (
        <Button
          type="text"
          icon={<MenuOutlined aria-hidden />}
          aria-label={t.common.openMenu}
          onClick={() => {
            setMobileSiderOpen(true);
          }}
        />
      ) : (
        <span />
      )}
      <Space size="small">
        <ConnectionStatus live={live} compact={phone} />
        <ModeSwitch />
        {phone ? null : <Typography.Text>{identity?.name}</Typography.Text>}
      </Space>
    </Layout.Header>
  );
}
