import { KeyOutlined, LogoutOutlined, UserOutlined } from "@ant-design/icons";
import { useGetIdentity, useLogout } from "@refinedev/core";
import { Avatar, Button, Dropdown, Grid } from "antd";
import { useNavigate } from "react-router";

import { t } from "../i18n/ru";

const initials = (name: string | undefined) =>
  (name ?? "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");

/** Меню пользователя в шапке (как в Linear/Intercom): профиль, смена пароля, выход. */
export function UserMenu() {
  const { data: identity } = useGetIdentity<{ name: string }>();
  const { mutate: logout } = useLogout();
  const navigate = useNavigate();
  const phone = Grid.useBreakpoint().sm === false;
  const items = [
    { key: "profile", icon: <UserOutlined aria-hidden />, label: t.nav.profile },
    { key: "password", icon: <KeyOutlined aria-hidden />, label: t.nav.changePassword },
    { type: "divider" as const },
    { key: "logout", icon: <LogoutOutlined aria-hidden />, label: t.nav.logout },
  ];
  const onClick = ({ key }: { key: string }) => {
    if (key === "profile") void navigate("/profile");
    else if (key === "password") void navigate("/change-password");
    else logout();
  };
  return (
    <Dropdown menu={{ items, onClick }} trigger={["click"]} placement="bottomRight">
      <Button type="text" aria-label={`${t.nav.userMenu}: ${identity?.name ?? ""}`}>
        <Avatar size="small" aria-hidden>
          {initials(identity?.name) || <UserOutlined />}
        </Avatar>
        {phone ? null : <span>{identity?.name}</span>}
      </Button>
    </Dropdown>
  );
}
