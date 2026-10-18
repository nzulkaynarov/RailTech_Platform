import { ExportOutlined, MenuOutlined } from "@ant-design/icons";
import { useThemedLayoutContext } from "@refinedev/antd";
import { useCan, useGetIdentity } from "@refinedev/core";
import { Alert, Badge, Button, Grid, Layout, Space, message, theme } from "antd";
import { useState } from "react";
import { Link } from "react-router";

import { useSystemStatus } from "../api/adminQueries";
import { ssoToken } from "../api/generated/crm";
import { ApiError } from "../api/http";

import { ModeSwitch } from "../components/ModeSwitch";
import { useEventStream } from "../hooks/useEventStream";
import { useLeadAlertHandler } from "../hooks/useLeadAlerts";
import { criticalFailures, headerHealth, type HeaderTone } from "../domain/systemHealth";
import { errorText, t } from "../i18n/ru";
import { UserMenu } from "./UserMenu";

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
  // Живая область — обёртка, а не сама ссылка: у `<a>` роль status недопустима (axe aria-allowed-role).
  return (
    <span role="status">
      <Link to="/system" title={t.health.hint}>
        <Badge status={BADGE[health.tone]} text={compact ? null : health.label} />
        {compact ? <span className="sr-only">{health.label}</span> : null}
      </Link>
    </span>
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
  // На телефоне в шапке только самое нужное: статус точкой, режим, аватар (имя — в меню).
  const phone = screens.sm === false;
  const { data: canSystem } = useCan({ resource: "system", action: "list" });
  const admin = Boolean(canSystem?.can);

  const [ssoLoading, setSsoLoading] = useState(false);

  const handleGoToErp = async () => {
    setSsoLoading(true);
    try {
      const data = await ssoToken();
      window.location.href = `${data.redirect_url}#token=${data.token}`;
    } catch (err) {
      void message.error(
        errorText(err instanceof ApiError ? err.code : undefined, t.sso.goToErpFailed),
      );
    } finally {
      setSsoLoading(false);
    }
  };

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
          <Button
            icon={<ExportOutlined aria-hidden />}
            loading={ssoLoading}
            onClick={() => void handleGoToErp()}
            title={t.sso.goToErpHint}
            aria-label={t.sso.goToErp}
          >
            {phone ? t.sso.goToErpShort : t.sso.goToErp}
          </Button>
          <ModeSwitch />
          <UserMenu />
        </Space>
      </Layout.Header>
      {admin ? <CriticalBanner /> : null}
    </>
  );
}
