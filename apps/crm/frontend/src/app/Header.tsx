import { useGetIdentity } from "@refinedev/core";
import { Badge, Layout, Space, theme, Typography } from "antd";

import { ModeSwitch } from "../components/ModeSwitch";
import { useEventStream } from "../hooks/useEventStream";
import { t } from "../i18n/ru";

export function Header() {
  const { data: identity } = useGetIdentity<{ name: string }>();
  const live = useEventStream(Boolean(identity));
  const { token } = theme.useToken();
  return (
    <Layout.Header
      style={{
        display: "flex",
        justifyContent: "flex-end",
        alignItems: "center",
        padding: "0 16px",
        background: token.colorBgContainer,
      }}
    >
      <Space wrap>
        <Badge status={live ? "success" : "default"} text={t.common.live} />
        <ModeSwitch />
        <Typography.Text>{identity?.name}</Typography.Text>
      </Space>
    </Layout.Header>
  );
}
