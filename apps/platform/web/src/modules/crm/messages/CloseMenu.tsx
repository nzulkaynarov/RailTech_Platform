import { Button, Dropdown } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ChevronDownIcon } from "../../../shared/ui/lucide";
import { CloseDialog, type CloseKind } from "./CloseDialogs";

/**
 * Одно меню «Закрыть» над лидом (LH-1): «Заключено» и «Отказ» — если лид взят этим сотрудником, «Спам», «Тест», «Дубль» —
 * пока лид ничей или у него. Каждый пункт открывает окно с одним подтверждением. Кнопка вторичная: главная на экране —
 * «Забрать» или «Ответить».
 */
export function CloseMenu({
  lead,
  name,
  close,
  discard,
}: {
  lead: string;
  name: string;
  close: boolean;
  discard: boolean;
}) {
  const { t } = useTranslation("messages");
  const [open, setOpen] = useState<CloseKind | null>(null);
  const items = [
    ...(close
      ? [
          { key: "won", label: t("close.won") },
          { key: "lost", label: t("close.lost") },
        ]
      : []),
    ...(close && discard ? [{ type: "divider" as const }] : []),
    ...(discard
      ? [
          { key: "spam", label: t("discard.spam.title") },
          { key: "test", label: t("discard.test.title") },
          { key: "duplicate", label: t("discard.duplicate.title") },
        ]
      : []),
  ];
  if (!close && !discard) return null;
  return (
    <>
      <Dropdown
        trigger={["click"]}
        menu={{
          items,
          onClick: ({ key }) => {
            setOpen(key as CloseKind);
          },
        }}
      >
        <Button aria-label={`${t("close.menu")}: ${name}`}>
          {t("close.menu")} <ChevronDownIcon />
        </Button>
      </Dropdown>
      {open ? (
        <CloseDialog
          lead={lead}
          kind={open}
          onClose={() => {
            setOpen(null);
          }}
        />
      ) : null}
    </>
  );
}
