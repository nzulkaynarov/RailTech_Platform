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
 * «Настройка CRM 5/8 — продолжить» на главной админа (scope-аудит §4): одна строка с полосой,
 * по нажатию раскрывается список «что ещё не сделано и куда идти». Пункты «бот» и «модели» —
 * из тех же проверок, что «Состояние системы». Не видна, когда всё готово, и после «Скрыть».
 */
export function SetupChecklistCard() {
  const { data: can } = useCan({ resource: "settings", action: "list" });
  const [hidden, setHidden] = useState(readHidden);
  const [open, setOpen] = useState(false);
  const query = useSetupChecklist(Boolean(can?.can) && !hidden);
  const data = query.data;
  if (!can?.can || hidden || !data || data.done >= data.total) return null;
  const fill = (text: string) =>
    text.replace("{done}", String(data.done)).replace("{total}", String(data.total));
  const title = fill(t.checklist.title);
  return (
    <Card className="setup-checklist" size="small">
      <div className="setup-checklist-bar">
        <Typography.Text strong className="setup-checklist-title">
          {fill(t.checklist.bar)}
        </Typography.Text>
        <Progress
          className="setup-checklist-progress"
          percent={Math.round((data.done / data.total) * 100)}
          showInfo={false}
          size="small"
          aria-label={title}
        />
        <Button
          type="link"
          size="small"
          aria-expanded={open}
          onClick={() => {
            setOpen((v) => !v);
          }}
        >
          {open ? t.checklist.collapse : t.checklist.continue}
        </Button>
        <Button
          type="link"
          size="small"
          onClick={() => {
            writeHidden();
            setHidden(true);
          }}
        >
          {t.checklist.hide}
        </Button>
      </div>
      {open ? (
        <List
          size="small"
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
      ) : null}
    </Card>
  );
}
