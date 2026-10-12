import { CheckCircleFilled, ExclamationCircleOutlined } from "@ant-design/icons";
import { useCan } from "@refinedev/core";
import { Button, Card, List, Progress, Typography } from "antd";
import { useState } from "react";
import { Link } from "react-router";

import { useSetupChecklist } from "../api/systemQueries";
import { t } from "../i18n/ru";
import "../pages/setup/setup.css";

const STORAGE_KEY = "rt.setupChecklist.hidden";

function readHidden(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

function writeHidden(): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, "1");
  } catch {
    // Хранилище недоступно (приватный режим) — карточка скроется до перезагрузки.
  }
}

/**
 * «Настройка CRM — N из M» на главной админа (scope-аудит §4): что ещё не сделано и куда идти.
 * Не видна, когда всё готово, вне режима «Админ» и после «Скрыть».
 */
export function SetupChecklistCard() {
  const { data: can } = useCan({ resource: "settings", action: "list" });
  const [hidden, setHidden] = useState(readHidden);
  const query = useSetupChecklist(Boolean(can?.can) && !hidden);
  const data = query.data;
  if (!can?.can || hidden || !data || data.done >= data.total) return null;
  const title = t.checklist.title
    .replace("{done}", String(data.done))
    .replace("{total}", String(data.total));
  return (
    <Card
      className="setup-checklist"
      title={<h2 className="section-title">{title}</h2>}
      extra={
        <Button
          type="link"
          onClick={() => {
            writeHidden();
            setHidden(true);
          }}
        >
          {t.checklist.hide}
        </Button>
      }
    >
      <Progress
        percent={Math.round((data.done / data.total) * 100)}
        showInfo={false}
        aria-label={title}
      />
      <List
        dataSource={data.items}
        renderItem={(item) => (
          <List.Item actions={item.done ? [] : [<Link to={item.link}>{t.checklist.open}</Link>]}>
            <Typography.Text>
              {item.done ? (
                <CheckCircleFilled aria-label={t.checklist.done} className="setup-done" />
              ) : (
                <ExclamationCircleOutlined aria-label={t.checklist.todo} />
              )}{" "}
              {t.checklist.items[item.key] ?? item.key}
            </Typography.Text>
          </List.Item>
        )}
      />
    </Card>
  );
}
