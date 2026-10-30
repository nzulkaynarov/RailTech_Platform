import { CopyOutlined } from "@ant-design/icons";
import { App } from "antd";
import type React from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { docNumberToPath } from "../lib/docNumber";
import "./ui.css";

export interface DocNumberProps {
  number: string;
  base?: string;
  /** Включить кнопку быстрого копирования номера (по умолчанию true) */
  copyable?: boolean;
}

/** Буфер обмена есть только в защищённом контексте (https или localhost). */
function canCopy(): boolean {
  return typeof navigator !== "undefined" && Boolean((navigator as Partial<Navigator>).clipboard);
}

/**
 * Бизнес-номер объекта (`ПР-2026-104`): не переносится по строкам, цифры одной ширины, не переводится автопереводчиком.
 * Рядом — кнопка «Скопировать номер» (тост об итоге словами); без буфера обмена (http) кнопки нет.
 * С `base` — ссылка на карточку: `<base>/<номер в кодировке URL>` (SPEC-v3 §6.3, docs/architecture/platform-frontend.md §6).
 */
export function DocNumber({ number, base, copyable = true }: DocNumberProps) {
  const { t } = useTranslation("ui");
  const { message } = App.useApp();
  const handleCopy = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    navigator.clipboard.writeText(number).then(
      () => {
        void message.success(t("docNumber.copied"));
      },
      () => {
        void message.error(t("docNumber.copyFailed"));
      },
    );
  };

  const numberNode = (
    <span className="pf-docnum" translate="no">
      {number}
    </span>
  );

  const mainContent = base ? (
    <Link to={`${base.replace(/\/$/, "")}/${docNumberToPath(number)}`} className="pf-link">
      {numberNode}
    </Link>
  ) : (
    numberNode
  );

  if (!copyable || !canCopy()) {
    return mainContent;
  }

  return (
    <span
      className="pf-docnum-wrap"
      style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
    >
      {mainContent}
      <button
        type="button"
        onClick={handleCopy}
        className="pf-docnum-copy-btn"
        title={t("docNumber.copy")}
        aria-label={t("docNumber.copyNumber", { number })}
        style={{
          border: "none",
          background: "transparent",
          padding: "0 2px",
          cursor: "pointer",
          color: "#6e6e6e",
          display: "inline-flex",
          alignItems: "center",
          fontSize: 12,
          lineHeight: 1,
        }}
      >
        <CopyOutlined />
      </button>
    </span>
  );
}
