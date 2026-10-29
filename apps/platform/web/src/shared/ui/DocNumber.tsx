import { CopyOutlined } from "@ant-design/icons";
import { message } from "antd";
import type React from "react";
import { Link } from "react-router";

import { docNumberToPath } from "../lib/docNumber";
import "./ui.css";

export interface DocNumberProps {
  number: string;
  base?: string;
  /** Включить кнопку быстрого копирования номера (по умолчанию true) */
  copyable?: boolean;
}

/**
 * Бизнес-номер объекта (`ПР-2026-104`): не переносится по строкам, цифры одной ширины, не переводится автопереводчиком.
 * Поддерживает быстрое копирование в буфер по клику на иконку копирования с тостом message.success.
 * С `base` — ссылка на карточку: `<base>/<номер в кодировке URL>` (SPEC-v3 §6.3, docs/architecture/platform-frontend.md §6).
 */
export function DocNumber({ number, base, copyable = true }: DocNumberProps) {
  const handleCopy = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (typeof navigator !== "undefined") {
      void navigator.clipboard.writeText(number).then(() => {
        void message.success("Номер скопирован");
      });
    }
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

  if (!copyable) {
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
        title="Скопировать номер"
        aria-label={`Скопировать номер ${number}`}
        style={{
          border: "none",
          background: "transparent",
          padding: "0 2px",
          cursor: "pointer",
          color: "#8c8c8c",
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
