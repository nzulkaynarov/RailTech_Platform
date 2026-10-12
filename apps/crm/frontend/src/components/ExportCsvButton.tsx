import { DownloadOutlined } from "@ant-design/icons";
import { App as AntApp, Button } from "antd";
import { useState } from "react";

import { usePermissionsQuery } from "../api/queries";
import { downloadCsv } from "../api/templateQueries";
import { allowed } from "../app/providers/access";
import { t } from "../i18n/ru";

type Props = { target: Parameters<typeof downloadCsv>[0] };

/** «Экспорт CSV» с текущими фильтрами списка; видна только с правом `export:read` (админ). */
export function ExportCsvButton({ target }: Props) {
  const perms = usePermissionsQuery();
  const { message } = AntApp.useApp();
  const [busy, setBusy] = useState(false);
  if (!allowed(perms.data, "export", "read")) return null;
  const run = async () => {
    setBusy(true);
    try {
      await downloadCsv(target);
      void message.success(t.exportCsv.done);
    } catch {
      void message.error(t.exportCsv.failed);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Button icon={<DownloadOutlined />} loading={busy} onClick={() => void run()}>
      {t.exportCsv.button}
    </Button>
  );
}
