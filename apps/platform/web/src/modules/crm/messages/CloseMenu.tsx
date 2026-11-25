import { Button, Dropdown, Menu } from "antd";
import { useId, useRef, useState } from "react";
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
  inline = false,
}: {
  lead: string;
  name: string;
  close: boolean;
  discard: boolean;
  /** Пункты раскрываются в потоке под кнопкой, а не поверх содержимого (карточка лида: меню не закрывает сообщения). */
  inline?: boolean;
}) {
  const { t } = useTranslation("messages");
  const [open, setOpen] = useState<CloseKind | null>(null);
  const [expanded, setExpanded] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuId = useId();
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
  const dialog = open ? (
    <CloseDialog
      lead={lead}
      kind={open}
      onClose={() => {
        setOpen(null);
        // после окна фокус возвращается на «Закрыть», а не пропадает в начало страницы
        buttonRef.current?.focus();
      }}
    />
  ) : null;
  if (inline) {
    return (
      <>
        <Button
          ref={buttonRef}
          aria-label={`${t("close.menu")}: ${name}`}
          aria-expanded={expanded}
          aria-controls={expanded ? menuId : undefined}
          onKeyDown={(event) => {
            if (event.key === "Escape" && expanded) {
              event.stopPropagation();
              setExpanded(false);
            }
          }}
          onClick={() => {
            setExpanded((value) => !value);
          }}
        >
          {t("close.menu")} <ChevronDownIcon />
        </Button>
        {expanded ? (
          <Menu
            id={menuId}
            className="pf-crm-close-inline"
            onKeyDown={(event) => {
              if (event.key !== "Escape") return;
              event.stopPropagation();
              setExpanded(false);
              buttonRef.current?.focus();
            }}
            selectable={false}
            items={items}
            onClick={({ key }) => {
              setExpanded(false);
              setOpen(key as CloseKind);
            }}
          />
        ) : null}
        {dialog}
      </>
    );
  }
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
      {dialog}
    </>
  );
}
