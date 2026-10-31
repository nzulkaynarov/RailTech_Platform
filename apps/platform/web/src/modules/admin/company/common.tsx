import type { UseQueryResult } from "@tanstack/react-query";
import { Alert, Button, Modal, Skeleton, Table } from "antd";
import type { TableColumnsType } from "antd";
import { type ReactNode, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { ApiError } from "../../../shared/api/errors";
import { Consequence } from "../../../shared/ui/Consequence";
import { ContextualSaveBar } from "../../../shared/ui/ContextualSaveBar";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { FilePicker } from "../../../shared/ui/FileField";
import { companyErrorText, isCompanyNotSet, missingBlocks } from "./errors";

import "./company.css";

/** Заголовок вкладки: `h2` и пояснение `#595959` (на странице один `h1` — «Компания»). */
export function TabHeader({ title, hint }: { title: string; hint?: string }) {
  return (
    <header className="pf-co-head">
      <h2 className="pf-co-title">{title}</h2>
      {hint ? <p className="pf-co-hint">{hint}</p> : null}
    </header>
  );
}

/**
 * Данные вкладки: загрузка — скелетон, ошибка — слово и «Повторить», своя компания в ERP ещё не создана — пустое
 * состояние с действием «Проверить снова» (мастер первого запуска — отдельная задача).
 */
export function QueryGate<T>({
  query,
  children,
}: {
  query: UseQueryResult<T, ApiError>;
  children: (data: T) => ReactNode;
}) {
  const { t } = useTranslation("company");
  if (query.isPending) return <Skeleton active paragraph={{ rows: 6 }} title={false} />;
  if (query.isError) {
    if (isCompanyNotSet(query.error)) {
      return (
        <EmptyState
          title={t("notSet.title")}
          text={t("notSet.text")}
          action={
            <Button
              onClick={() => {
                void query.refetch();
              }}
            >
              {t("notSet.action")}
            </Button>
          }
        />
      );
    }
    return (
      <Alert
        type="error"
        showIcon
        role="alert"
        message={companyErrorText(t, query.error)}
        action={
          <Button
            size="small"
            onClick={() => {
              void query.refetch();
            }}
          >
            {t("retry")}
          </Button>
        }
      />
    );
  }
  return <>{children(query.data)}</>;
}

/**
 * Сохранение вкладки: бар несохранённого (`ContextualSaveBar`) в конце формы с подписью действия («Сохранить
 * реквизиты»), над ним — ошибка последнего сохранения словами и блок «Что произойдёт». Отдельной кнопки под формой
 * нет: бар и есть кнопка (UX-1b, S6). Уход с несохранёнными правками — в том числе на другую вкладку — спрашивает.
 */
export function SaveBlock({
  label,
  loading,
  disabled,
  error,
  consequence,
  onClick,
  onDiscard,
  dirty,
}: {
  label: string;
  loading?: boolean;
  disabled?: boolean;
  /** Есть изменения (для бара сохранения); по умолчанию — «сохранить можно» */
  dirty?: boolean;
  error?: unknown;
  consequence: readonly ReactNode[];
  /** Своё сохранение; без него — отправка формы, в которой стоит блок */
  onClick?: () => void;
  onDiscard: () => void;
}) {
  const { t } = useTranslation("company");
  const anchorRef = useRef<HTMLDivElement>(null);

  const handleSave = () => {
    if (onClick) {
      onClick();
    } else {
      anchorRef.current?.closest("form")?.requestSubmit();
    }
  };

  return (
    <>
      <div ref={anchorRef} className="pf-co-save">
        {error ? (
          <Alert type="error" showIcon role="alert" message={companyErrorText(t, error)} />
        ) : null}
        <Consequence items={consequence} />
      </div>
      <ContextualSaveBar
        className="pf-co-save-dock"
        visible={dirty ?? !disabled}
        saveLabel={label}
        loading={loading ?? false}
        disabled={disabled ?? false}
        guardParams={["tab"]}
        onSave={handleSave}
        onDiscard={onDiscard}
      />
    </>
  );
}

/** Образец документа в изолированной рамке: без скриптов и без доступа к странице (`sandbox` без разрешений). */
export function PreviewFrame({
  html: next,
  title,
  loading,
}: {
  html: string | undefined;
  title: string;
  loading?: boolean;
}) {
  const { t } = useTranslation("company");
  // Пока считается новый образец, показывается прежний: рамка не мигает на каждый ввод.
  const [shown, setShown] = useState(next);
  if (next !== undefined && next !== shown) setShown(next);
  const html = next ?? shown;
  return (
    <div className="pf-co-preview" aria-busy={loading ? "true" : "false"}>
      {html ? (
        <iframe className="pf-co-frame" title={title} sandbox="" srcDoc={html} />
      ) : (
        <p className="pf-co-hint pf-co-preview-empty">
          {loading ? t("preview.loading") : t("preview.empty")}
        </p>
      )}
    </div>
  );
}

const LOGO_TYPES = "image/png,image/jpeg,image/webp,image/svg+xml";
const LOGO_MAX_BYTES = 2 * 1024 * 1024;

/** Логотип: образец, «Загрузить» (файл уходит в BFF как `multipart/form-data`) и «Удалить». Размер проверяется до отправки. */
export function LogoField({
  url,
  label,
  uploading,
  error,
  onUpload,
  onDelete,
  deleting,
}: {
  url: string | null;
  label: string;
  uploading: boolean;
  error: unknown;
  onUpload: (file: File) => void;
  onDelete?: () => void;
  deleting?: boolean;
}) {
  const { t } = useTranslation("company");
  const id = useId();
  const [tooBig, setTooBig] = useState(false);
  const [broken, setBroken] = useState<string | null>(null);
  const showImage = url !== null && broken !== url;
  return (
    <div className="pf-co-logo" role="group" aria-labelledby={`${id}-label`}>
      <span id={`${id}-label`} className="pf-co-logo-label">
        {label}
      </span>
      <div className="pf-co-logo-row">
        <div className="pf-co-logo-box">
          {showImage ? (
            <img
              src={url}
              alt={t("logo.alt")}
              onError={() => {
                setBroken(url);
              }}
            />
          ) : (
            <span className="pf-co-hint">{url ? t("logo.unavailable") : t("logo.none")}</span>
          )}
        </div>
        <div className="pf-co-logo-actions">
          <FilePicker
            accept={LOGO_TYPES}
            inputLabel={t("logo.file", { label })}
            loading={uploading}
            buttonLabel={url ? t("logo.replace") : t("logo.upload")}
            onPick={(files) => {
              const file = files[0];
              if (!file) return;
              if (file.size > LOGO_MAX_BYTES) {
                setTooBig(true);
                return;
              }
              setTooBig(false);
              onUpload(file);
            }}
          />
          {url && onDelete ? (
            <Button type="link" danger loading={deleting} onClick={onDelete}>
              {t("logo.delete")}
            </Button>
          ) : null}
        </div>
      </div>
      <p className="pf-co-hint" style={{ margin: 0 }}>
        {t("logo.hint")}
      </p>
      {tooBig ? (
        <Alert type="error" showIcon role="alert" message={t("errors.reason.file_too_large")} />
      ) : null}
      {error ? (
        <Alert type="error" showIcon role="alert" message={companyErrorText(t, error)} />
      ) : null}
    </div>
  );
}

/** Какие обязательные блоки не хватает в тексте шаблона и что с этим делать (пусто, если ошибка не про блоки). */
function MissingBlocks({ error }: { error: unknown }) {
  const { t } = useTranslation("company");
  const blocks = missingBlocks(error);
  if (blocks.length === 0) return null;
  return (
    <div>
      <p style={{ margin: "0 0 4px" }}>{t("errors.missingBlocks.title")}</p>
      <ul style={{ margin: "0 0 4px", paddingLeft: 20 }}>
        {blocks.map((block) => (
          <li key={block.code}>
            {block.label} — <code className="pf-co-mono">{`{{${block.code}}}`}</code>
          </li>
        ))}
      </ul>
      <p style={{ margin: 0 }}>{t("errors.missingBlocks.hint")}</p>
    </div>
  );
}

/**
 * Окно с формой: «Отмена» и главная кнопка окна, связанная с формой атрибутом `form` (кнопка вне `<form>`). Заголовок —
 * имя действия; блок «Что произойдёт» (если есть) лежит под полями, внутри формы.
 */
export function FormModal({
  open,
  title,
  formId,
  submitLabel,
  saving,
  error,
  onCancel,
  width = 560,
  readOnly = false,
  children,
}: {
  open: boolean;
  title: string;
  formId: string;
  submitLabel: string;
  saving: boolean;
  error?: unknown;
  onCancel: () => void;
  width?: number;
  /** Просмотр без права на изменение: вместо «Отмена» и главной кнопки — «Закрыть» */
  readOnly?: boolean;
  children: ReactNode;
}) {
  const { t } = useTranslation("company");
  return (
    <Modal
      open={open}
      title={title}
      width={width}
      onCancel={onCancel}
      destroyOnHidden
      maskClosable={false}
      footer={
        readOnly
          ? [
              <Button key="close" onClick={onCancel}>
                {t("close")}
              </Button>,
            ]
          : [
              <Button key="cancel" onClick={onCancel}>
                {t("cancel")}
              </Button>,
              <Button key="submit" type="primary" htmlType="submit" form={formId} loading={saving}>
                {submitLabel}
              </Button>,
            ]
      }
    >
      {error ? (
        <Alert
          type="error"
          showIcon
          role="alert"
          message={companyErrorText(t, error)}
          description={
            missingBlocks(error).length > 0 ? <MissingBlocks error={error} /> : undefined
          }
          style={{ marginBottom: 16 }}
        />
      ) : null}
      {children}
    </Modal>
  );
}

/** Подтверждение опасного действия: что произойдёт, «Отмена» и кнопка действия (удаление, решение по запросу). */
export function ConfirmModal({
  open,
  title,
  items,
  okLabel,
  danger = false,
  loading,
  error,
  onOk,
  onCancel,
  children,
}: {
  open: boolean;
  title: string;
  items: readonly ReactNode[];
  okLabel: string;
  danger?: boolean;
  loading: boolean;
  error?: unknown;
  onOk: () => void;
  onCancel: () => void;
  children?: ReactNode;
}) {
  const { t } = useTranslation("company");
  return (
    <Modal
      open={open}
      title={title}
      onCancel={onCancel}
      destroyOnHidden
      maskClosable={false}
      footer={[
        <Button key="cancel" onClick={onCancel}>
          {t("cancel")}
        </Button>,
        <Button key="ok" type="primary" danger={danger} loading={loading} onClick={onOk}>
          {okLabel}
        </Button>,
      ]}
    >
      <div className="pf-co-save" style={{ maxWidth: "none" }}>
        {children}
        {error ? (
          <Alert type="error" showIcon role="alert" message={companyErrorText(t, error)} />
        ) : null}
        <Consequence items={items} />
      </div>
    </Modal>
  );
}

/**
 * Таблица настройки: прокручиваемая область доступна с клавиатуры (регион с именем), пусто — словами с действием
 * (SPEC-v3 §7); страницы — только когда задан `pageSize` (справочник стран на 250 строк), иначе без пагинации.
 */
export function ListTable<T extends object>({
  label,
  columns,
  data,
  rowKey,
  loading,
  empty,
  pageSize,
}: {
  label: string;
  columns: TableColumnsType<T>;
  data: readonly T[];
  rowKey: (row: T) => string;
  loading?: boolean;
  empty: { title: string; text: string; action?: ReactNode };
  pageSize?: number;
}) {
  return (
    <div className="pf-co-table-wrap" tabIndex={0} role="region" aria-label={label}>
      <Table<T>
        size="middle"
        pagination={pageSize ? { pageSize, hideOnSinglePage: true, showSizeChanger: false } : false}
        scroll={{ x: "max-content" }}
        loading={loading}
        columns={columns}
        dataSource={data}
        rowKey={rowKey}
        locale={{
          emptyText: (
            <EmptyState
              level={3}
              compact
              title={empty.title}
              text={empty.text}
              action={empty.action}
            />
          ),
        }}
      />
    </div>
  );
}

/**
 * Доступ «чтение» к `company.settings`: поля и кнопки изменения заблокированы (`fieldset disabled`), а вкладки,
 * переключатели видов и предпросмотры остаются снаружи — читатель их листает. `block` — без колонки с отступами.
 */
export function ReadOnlyFence({
  children,
  block = false,
}: {
  children: ReactNode;
  block?: boolean;
}) {
  const { me } = useAuth();
  return (
    <fieldset
      disabled={!canEdit(me, "company.settings")}
      className={block ? "pf-co-fieldset-reset" : "pf-co-fieldset-reset pf-co-fieldset-stack"}
    >
      {children}
    </fieldset>
  );
}
