import { ArrowLeftOutlined } from "@ant-design/icons";
import { Space, Typography } from "antd";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { t } from "../i18n/ru";

type Props = { title: ReactNode; back?: string; extra?: ReactNode; children?: ReactNode };

/** Шапка страницы: «Назад» (для карточек), заголовок, основные действия справа (U-10). */
export function PageHeader({ title, back, extra, children }: Props) {
  return (
    <div className="page-header">
      {back ? (
        <Link to={back} className="page-back">
          <ArrowLeftOutlined /> {t.common.back}
        </Link>
      ) : null}
      <Space wrap align="center" className="page-title-row">
        <Typography.Title level={4} style={{ margin: 0 }}>
          {title}
        </Typography.Title>
        {extra}
      </Space>
      {children}
    </div>
  );
}
