import { MenuOutlined } from "@ant-design/icons";
import { useThemedLayoutContext } from "@refinedev/antd";
import { useCan, useGetIdentity } from "@refinedev/core";
import { Alert, Badge, Button, Grid, Layout, Space, theme, Typography } from "antd";
import { Link } from "react-router";

import { useSystemStatus } from "../api/adminQueries";

import { ModeSwitch } from "../components/ModeSwitch";
import { useEventStream } from "../hooks/useEventStream";
import { useLeadAlertHandler } from "../hooks/useLeadAlerts";
import { criticalFailures, headerHealth, type HeaderTone } from "../domain/systemHealth";
import { t } from "../i18n/ru";

const BADGE: Record<HeaderTone, "success" | "warning" | "error"> = {
  ok: "success",
  warn: "warning",
  fail: "error",
};

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
 * Здоровье системы для админа (тот же `GET /system/status`, что «Состояние»): ссылка на `/system`.
 * Нет связи с CRM — показываем это: устаревшему «Онлайн» верить нельзя.
 */
function SystemHealth({ live, compact }: { live: boolean; compact: boolean }) {
  const query = useSystemStatus();
  if (!live || !query.data) return <ConnectionStatus live={live} compact={compact} />;
  const health = headerHealth(query.data);
  return (
    <Link to="/system" title={t.health.hint} role="status">
      <Badge status={BADGE[health.tone]} text={compact ? null : health.label} />
      {compact ? <span className="sr-only">{health.label}</span> : null}
    </Link>
  );
}

/** Красная полоса под шапкой, когда клиенты не получают ответов (бот или модель диалога). */
export function CriticalBanner() {
  const query = useSystemStatus();
  const failures = query.data ? criticalFailures(query.data) : [];
  if (!failures.length) return null;
  const names = failures.map((c) => t.health.short[c.key] ?? c.title).join(", ");
  return (
    <Alert
      type="error"
      banner
      showIcon
      message={t.health.bannerTitle.replace("{names}", names)}
      description={failures.map((c) => c.reason).join(" ")}
      action={<Link to="/system">{t.health.bannerAction}</Link>}
    />
  );
}

/**
 * Шапка. На экранах уже `lg` меню Refine — выдвижная панель; кнопка открытия здесь,
 * а не плавающая поверх заголовка страницы (дизайн-аудит 2026-10-11, отчёт 2).
 */
export function Header() {
  const { data: identity } = useGetIdentity<{ name: string }>();
  const live = useEventStream(Boolean(identity), useLeadAlertHandler());
  const { token } = theme.useToken();
  const screens = Grid.useBreakpoint();
  const { setMobileSiderOpen } = useThemedLayoutContext();
  // Та же граница, что у ThemedSider: меню-панель, пока брейкпоинт `lg` не достигнут.
  const drawerMenu = screens.lg === false;
  // На телефоне в шапке только самое нужное: статус точкой, переключатель режима; имя — в профиле.
  const phone = screens.sm === false;
  const { data: canSystem } = useCan({ resource: "system", action: "list" });
  const admin = Boolean(canSystem?.can);
  return (
    <>
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
          {admin ? (
            <SystemHealth live={live} compact={phone} />
          ) : (
            <ConnectionStatus live={live} compact={phone} />
          )}
          <ModeSwitch />
          {phone ? null : <Typography.Text>{identity?.name}</Typography.Text>}
        </Space>
      </Layout.Header>
      {admin ? <CriticalBanner /> : null}
    </>
  );
}
