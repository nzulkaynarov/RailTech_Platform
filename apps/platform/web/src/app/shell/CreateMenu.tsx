import { Button, Dropdown, type MenuProps } from "antd";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { PlusIcon } from "../../shared/ui/icons";
import { canEdit } from "../access";
import { useAuth } from "../auth/useAuth";

interface Kind {
  key: string;
  /** Нужен полный доступ хотя бы к одному разделу */
  resources: readonly string[];
  /** Форма есть; без адреса пункт виден и неактивен */
  to?: string;
}

const KINDS: readonly Kind[] = [
  { key: "lead", resources: ["crm.leads"] },
  { key: "request", resources: ["crm.clients"], to: "/crm/leads?status=wants_quote" },
  { key: "incoming", resources: ["eds.inbox.register"], to: "/eds/register" },
  { key: "letter", resources: ["eds.memo.create"], to: "/eds/new?type=letter" },
  { key: "memo", resources: ["eds.memo.create"], to: "/eds/new?type=memo" },
  { key: "statement", resources: ["eds.memo.create"], to: "/eds/new?type=statement" },
  { key: "report", resources: ["eds.memo.create"], to: "/eds/new?type=report" },
  { key: "purchase", resources: ["eds.memo.create"] },
  { key: "assignment", resources: ["eds.inbox"] },
  { key: "expense", resources: ["eds.memo.create"] },
];

/** Единая кнопка «Создать» (docs/product/NAVIGATION.md): виды по правам роли. */
export function CreateMenu({ block = false }: { block?: boolean }) {
  const { t } = useTranslation("shell");
  const { me } = useAuth();
  const navigate = useNavigate();
  const items: MenuProps["items"] = KINDS.filter((kind) =>
    kind.resources.some((resource) => canEdit(me, resource)),
  ).map((kind) => ({
    key: kind.key,
    disabled: kind.to === undefined,
    label:
      kind.to === undefined
        ? `${t(`create.kinds.${kind.key}`)} · ${t("create.soon")}`
        : t(`create.kinds.${kind.key}`),
  }));
  if (items.length === 0) return null;

  const open: MenuProps["onClick"] = ({ key }) => {
    const to = KINDS.find((kind) => kind.key === key)?.to;
    if (to) void navigate(to);
  };

  return (
    <Dropdown menu={{ items, onClick: open }} trigger={["click"]} placement="bottomLeft">
      {block ? (
        <Button type="primary" block icon={<PlusIcon />}>
          {t("create.label")}
        </Button>
      ) : (
        <Button
          type="primary"
          icon={<PlusIcon />}
          aria-label={t("create.label")}
          title={t("create.label")}
          className="pf-rail-create"
        />
      )}
    </Dropdown>
  );
}
