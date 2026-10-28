import { Alert, App } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { BackupsStatus } from "../../../shared/api/generated/model";
import {
  useGetBackups,
  useListExternalServices,
  useRequestBackup,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { OffsiteSection } from "./OffsitePanel";
import { ActionForm, ActionToggle, LevelTag, PanelState, PanelTitle } from "./parts";
import { useRefreshIntegrations } from "./refresh";

const MB = 1024 * 1024;

function BackupRequest({ backups }: { backups: BackupsStatus }) {
  const { t } = useTranslation("integrations");
  const { message } = App.useApp();
  const refresh = useRefreshIntegrations();
  const [open, setOpen] = useState(false);
  const request = useRequestBackup({
    mutation: {
      onSuccess: () => {
        refresh();
        setOpen(false);
        void message.success(t("storage.request.sent"));
      },
    },
  });
  const waiting = backups.requested_at !== null && !backups.request_stuck;
  return (
    <ActionToggle
      label={t("storage.request.button")}
      open={open}
      onToggle={setOpen}
      disabled={waiting}
    >
      <ActionForm
        id="backup"
        title={t("storage.request.title")}
        submitLabel={t("storage.request.submit")}
        needsPassword={false}
        pending={request.isPending}
        error={request.error}
        consequence={[
          t("storage.request.step1"),
          t("storage.request.step2"),
          t("storage.request.step3"),
        ]}
        onCancel={() => {
          setOpen(false);
        }}
        onSubmit={() => {
          request.mutate();
        }}
      />
    </ActionToggle>
  );
}

function BackupsBody({ backups, editable }: { backups: BackupsStatus; editable: boolean }) {
  const { t } = useTranslation("integrations");
  const { date, number } = useFormat();
  return (
    <section className="pf-int-block" aria-labelledby="storage-backups-title">
      <h4 id="storage-backups-title">{t("storage.backups.title")}</h4>
      <DefinitionList
        items={[
          {
            label: t("storage.backups.source"),
            value: t(`storage.backups.sourceValue.${backups.source}`),
          },
          {
            label: t("storage.backups.last"),
            value: backups.last_success_at
              ? date(backups.last_success_at, "datetime")
              : t("storage.backups.none"),
          },
          {
            label: t("storage.backups.state"),
            value: !backups.available
              ? t("storage.backups.stateValue.unavailable")
              : backups.last_success_at === null
                ? t("storage.backups.stateValue.empty")
                : backups.stale
                  ? t("storage.backups.stateValue.stale")
                  : t("storage.backups.stateValue.fresh"),
          },
          {
            label: t("storage.backups.daemon"),
            value: backups.daemon_alive
              ? t("storage.backups.daemonValue.alive")
              : t("storage.backups.daemonValue.down"),
          },
        ]}
      />
      {backups.error ? (
        <Alert
          type="warning"
          showIcon
          role="status"
          message={t(`storage.backups.error.${backups.error}`)}
        />
      ) : null}
      {backups.requested_at ? (
        <Alert
          type={backups.request_stuck ? "warning" : "info"}
          showIcon
          role="status"
          message={t(
            backups.request_stuck ? "storage.backups.stuck" : "storage.backups.requested",
            {
              date: date(backups.requested_at, "datetime"),
            },
          )}
        />
      ) : null}
      {backups.databases.length > 0 ? (
        <ul className="pf-int-list" aria-label={t("storage.backups.databases")}>
          {backups.databases.map((db) => (
            <li key={db.name}>
              <div className="pf-int-item-head">
                <span className="pf-int-item-title">{db.name}</span>
                <span className="pf-int-sub">
                  {db.last_success_at
                    ? date(db.last_success_at, "datetime")
                    : t("storage.backups.none")}
                </span>
              </div>
            </li>
          ))}
        </ul>
      ) : null}
      {backups.items.length > 0 ? (
        <ul className="pf-int-list" aria-label={t("storage.backups.items")}>
          {backups.items.map((item) => (
            <li key={item.name}>
              <div className="pf-int-item-head">
                <span className="pf-int-item-title">{item.name}</span>
                <span className="pf-int-sub">
                  {date(item.at, "datetime")} ·{" "}
                  {t("storage.backups.size", {
                    mb: number(item.size_bytes / MB, { fractionDigits: 1 }),
                  })}
                </span>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="pf-hint" style={{ margin: 0 }}>
          {t("storage.backups.noItems")}
        </p>
      )}
      {editable && backups.can_request ? <BackupRequest backups={backups} /> : null}
      {editable && !backups.can_request ? (
        <p className="pf-hint" style={{ margin: 0 }}>
          {t("storage.request.unavailable")}
        </p>
      ) : null}
    </section>
  );
}

function FilesService() {
  const { t } = useTranslation("integrations");
  const { date } = useFormat();
  const query = useListExternalServices();
  return (
    <section className="pf-int-block" aria-labelledby="storage-files-title">
      <h4 id="storage-files-title">{t("storage.files.title")}</h4>
      <PanelState query={query}>
        {(list) => {
          const s3 = list.items.find((service) => service.key === "s3");
          if (!s3)
            return (
              <p className="pf-hint" style={{ margin: 0 }}>
                {t("storage.files.none")}
              </p>
            );
          return (
            <div className="pf-int-form">
              <div className="pf-int-item-head">
                <span className="pf-int-item-title">{s3.title}</span>
                <LevelTag level={s3.status} />
              </div>
              <p className="pf-int-sub">{s3.purpose}</p>
              <p className="pf-int-sub">{s3.summary}</p>
              {s3.status !== "ok" && s3.hint ? (
                <p className="pf-int-sub">{t("services.hint", { hint: s3.hint })}</p>
              ) : null}
              <p className="pf-int-sub">
                {s3.checked_at
                  ? t("services.checkedAt", { date: date(s3.checked_at, "datetime") })
                  : t("services.neverChecked")}
              </p>
            </div>
          );
        }}
      </PanelState>
    </section>
  );
}

/** Карточка «Хранилище и бэкапы»: файлы (S3 из реестра сервисов), последние копии, «Сделать копию сейчас»,
 * внешняя копия на Google Drive (OPS-GDRIVE-2). */
export function StoragePanel({ editable }: { editable: boolean }) {
  const { t } = useTranslation("integrations");
  const query = useGetBackups();
  return (
    <div className="pf-panel-stack">
      <PanelTitle>{t("cards.storage.title")}</PanelTitle>
      <FilesService />
      <PanelState query={query}>
        {(backups) => <BackupsBody backups={backups} editable={editable} />}
      </PanelState>
      <OffsiteSection editable={editable} />
    </div>
  );
}
