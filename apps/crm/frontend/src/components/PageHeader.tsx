import { ArrowLeftOutlined } from "@ant-design/icons";
import { Button, Space, Typography } from "antd";
import type { ReactNode } from "react";
import { useLocation, useNavigate } from "react-router";

import { t } from "../i18n/ru";

type Props = { title: ReactNode; back?: string; extra?: ReactNode; children?: ReactNode };

/**
 * Шапка страницы: «Назад», заголовок, действия (аудит UI U-10). «Назад» возвращает туда,
 * откуда пришли (список с теми же фильтрами); при прямом заходе — на `back`.
 */
export function PageHeader({ title, back, extra, children }: Props) {
  const navigate = useNavigate();
  const location = useLocation();
  const goBack = () => {
    if (location.key !== "default") void navigate(-1);
    else if (back) void navigate(back);
  };
  return (
    <div className="page-header">
      {back ? (
        <Button type="link" className="page-back" icon={<ArrowLeftOutlined />} onClick={goBack}>
          {t.common.back}
        </Button>
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
