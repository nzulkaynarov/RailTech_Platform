import { useQueryClient } from "@tanstack/react-query";
import { Dropdown } from "antd";
import type { MenuProps } from "antd";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { getGetMeQueryKey, useLogout, useUpdateMe } from "../../shared/api/generated/platform-bff";
import type { Language, Me } from "../../shared/api/generated/model";
import { LANGUAGES } from "../../shared/i18n";
import { StaffAvatar } from "../../shared/ui/StaffAvatar";
import "../../shared/ui/shell.css";
import { roleCaption } from "./roleCaption";

/**
 * Меню аватара (SPEC-v3 §6.1 зона 6): профиль (страница `/me`, W15-H6), активная роль (если ролей несколько), язык ru/uz/en, смена пароля, выход.
 * Роль и язык сохраняются в `PATCH /me`; ответ — новый `Me` с пересчитанными модулями и разделами.
 */
export function AvatarMenu({ me, placement }: { me: Me; placement: "topLeft" | "topRight" }) {
  const { t } = useTranslation("shell");
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const update = useUpdateMe({
    mutation: {
      onSuccess: (next) => {
        queryClient.setQueryData(getGetMeQueryKey(), next);
      },
    },
  });
  const logout = useLogout({
    mutation: {
      onSettled: () => {
        queryClient.clear();
        void navigate("/login", { replace: true });
      },
    },
  });

  const caption = roleCaption(me, t);
  const selectedRole = me.active_role ?? "all";
  /** Выбранный пункт помечен для скринридера словом, а не только подсветкой. */
  const choice = (key: string, label: string, selected: boolean) => ({
    key,
    label: selected ? (
      <>
        {label}
        <span className="pf-sr-only">, {t("avatar.selected")}</span>
      </>
    ) : (
      label
    ),
  });
  const roleItems: NonNullable<MenuProps["items"]> =
    me.roles.length > 1
      ? [
          {
            type: "group",
            key: "roles",
            label: t("avatar.activeRole"),
            children: [
              choice("role:all", t("avatar.allRoles"), selectedRole === "all"),
              ...me.roles.map((role) =>
                choice(`role:${role.id}`, role.name, selectedRole === role.id),
              ),
            ],
          },
        ]
      : [];

  const items: MenuProps["items"] = [
    {
      type: "group",
      key: "account",
      label: (
        <span style={{ display: "block", lineHeight: "20px" }}>
          <span style={{ display: "block", fontWeight: 500, color: "#1f1f1f" }}>{me.name}</span>
          <span style={{ display: "block" }}>{me.email}</span>
        </span>
      ),
      children: [
        { key: "profile", label: t("avatar.profile") },
        { key: "password", label: t("avatar.changePassword") },
      ],
    },
    ...roleItems,
    {
      type: "group",
      key: "language",
      label: t("avatar.language"),
      children: LANGUAGES.map((lng) =>
        choice(`lang:${lng}`, t(`languages.${lng}`), me.language === lng),
      ),
    },
    { type: "divider" },
    { key: "logout", label: t("avatar.logout"), danger: true },
  ];

  const onClick: MenuProps["onClick"] = ({ key }) => {
    if (key === "profile") void navigate("/me");
    else if (key === "password") void navigate("/change-password");
    else if (key === "logout") logout.mutate();
    else if (key.startsWith("role:")) {
      const value = key.slice(5);
      update.mutate({ data: { active_role: value === "all" ? null : value } });
    } else if (key.startsWith("lang:")) {
      update.mutate({ data: { language: key.slice(5) as Language } });
    }
  };

  return (
    <Dropdown
      trigger={["click"]}
      placement={placement}
      menu={{
        items,
        onClick,
        selectable: true,
        selectedKeys: [`role:${selectedRole}`, `lang:${me.language}`],
        style: { minWidth: 220 },
      }}
    >
      <button
        type="button"
        className="pf-focusable"
        aria-label={t("avatar.open", { initials: me.initials, name: me.name, role: caption })}
        aria-haspopup="menu"
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 2,
          border: 0,
          background: "transparent",
          padding: 0,
          font: "inherit",
          cursor: "pointer",
        }}
      >
        <StaffAvatar initials={me.initials} src={me.avatar_url} />{" "}
        <span
          aria-hidden="true"
          style={{
            fontSize: 10,
            lineHeight: "12px",
            color: "#6e6e6e",
            maxWidth: 60,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {caption}
        </span>
      </button>
    </Dropdown>
  );
}
