import { Button } from "antd";
import { type DragEvent, type ReactNode, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { acceptLabel, matchesAccept } from "../lib/fileAccept";
import { formatFileSize } from "../lib/fileSize";

import "./file-field.css";

export interface FilePickerProps {
  /** id скрытого поля: к нему ведёт `label for` формы, к нему же обращаются тесты (`getByLabel(...).setInputFiles`). */
  id?: string | undefined;
  accept?: string | undefined;
  multiple?: boolean | undefined;
  disabled?: boolean | undefined;
  loading?: boolean | undefined;
  /** Текст кнопки; по умолчанию «Выбрать файл» или «Выбрать файлы». */
  buttonLabel?: ReactNode;
  /** Подпись скрытого поля, если у формы нет `label for` (например, «Выбрать файл: Логотип компании»). */
  inputLabel?: string | undefined;
  "aria-describedby"?: string | undefined;
  "aria-invalid"?: boolean | undefined;
  onPick: (files: File[]) => void;
}

/**
 * Кнопка выбора файла вместо системного `input type="file"` («Choose Files / No file chosen»): системное поле скрыто,
 * кнопка открывает диалог, выбранные файлы уходят в `onPick` без автозагрузки. Для полей со своим списком (загрузка
 * сразу после выбора, статусы) — эта кнопка; для обычной формы — `FileField` со списком выбранного.
 */
export function FilePicker({
  id,
  accept,
  multiple = false,
  disabled,
  loading,
  buttonLabel,
  inputLabel,
  "aria-describedby": describedBy,
  "aria-invalid": invalid,
  onPick,
}: FilePickerProps) {
  const { t } = useTranslation("ui");
  const input = useRef<HTMLInputElement>(null);
  return (
    <>
      <input
        ref={input}
        id={id}
        type="file"
        className="pf-sr-only"
        tabIndex={-1}
        accept={accept}
        multiple={multiple}
        disabled={disabled}
        aria-label={inputLabel}
        aria-describedby={describedBy}
        aria-invalid={invalid || undefined}
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          // Тот же файл можно выбрать ещё раз (после «Убрать» или ошибки)
          event.target.value = "";
          if (files.length > 0) onPick(files);
        }}
      />
      <Button
        className="pf-file-button"
        disabled={disabled}
        loading={loading}
        aria-describedby={describedBy}
        onClick={() => {
          input.current?.click();
        }}
      >
        {buttonLabel ?? (multiple ? t("file.chooseMany") : t("file.choose"))}
      </Button>
    </>
  );
}

export interface FileFieldProps {
  id?: string | undefined;
  /** Выбранные файлы — как раньше отдавало системное поле. */
  value: readonly File[];
  onChange: (files: File[]) => void;
  accept?: string | undefined;
  multiple?: boolean | undefined;
  /** Предел размера одного файла в байтах; больше — ошибка словами, файл не берётся. */
  maxSize?: number | undefined;
  disabled?: boolean | undefined;
  buttonLabel?: ReactNode;
  inputLabel?: string | undefined;
  "aria-describedby"?: string | undefined;
  "aria-invalid"?: boolean | undefined;
}

/**
 * Поле файла формы: кнопка «Выбрать файл» / «Выбрать файлы», список выбранного с размером и «Убрать», перетаскивание на
 * поле. Файлы не загружаются сами — форма получает `File[]` и отправляет их как раньше. Файл больше `maxSize` и
 * перетащенный файл не по `accept` не берутся: ошибка словами под кнопкой (`role="alert"`).
 */
export function FileField({
  id,
  value,
  onChange,
  accept,
  multiple = false,
  maxSize,
  disabled,
  buttonLabel,
  inputLabel,
  "aria-describedby": describedBy,
  "aria-invalid": invalid,
}: FileFieldProps) {
  const { t, i18n } = useTranslation("ui");
  const errorId = useId();
  const [problems, setProblems] = useState<string[]>([]);
  const [dragging, setDragging] = useState(false);

  // Тип проверяем у перетащенных файлов: диалог уже отфильтровал их по `accept`, а свои правила типа (например, «только .md»)
  // экран проверяет сам и пишет своими словами.
  const take = (files: File[], dropped: boolean) => {
    const found: string[] = [];
    const ok = files.filter((file) => {
      if (dropped && !matchesAccept(file, accept)) {
        found.push(t("file.wrongType", { name: file.name, accept: acceptLabel(accept ?? "") }));
        return false;
      }
      if (maxSize !== undefined && file.size > maxSize) {
        found.push(
          t("file.tooLarge", { name: file.name, max: formatFileSize(maxSize, i18n.language) }),
        );
        return false;
      }
      return true;
    });
    setProblems(found);
    if (ok.length === 0) return;
    onChange(multiple ? [...value, ...ok] : ok.slice(0, 1));
  };

  const drop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    if (disabled) return;
    const files = Array.from(event.dataTransfer.files);
    if (files.length > 0) take(multiple ? files : files.slice(0, 1), true);
  };

  const described = [describedBy, problems.length > 0 ? errorId : null].filter(Boolean).join(" ");

  return (
    <div
      className={`pf-file-field${dragging ? " pf-file-field-drag" : ""}`}
      onDragOver={(event) => {
        if (disabled) return;
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => {
        setDragging(false);
      }}
      onDrop={drop}
    >
      <div className="pf-file-field-row">
        <FilePicker
          id={id}
          accept={accept}
          multiple={multiple}
          disabled={disabled}
          buttonLabel={
            buttonLabel ?? (!multiple && value.length > 0 ? t("file.replace") : undefined)
          }
          inputLabel={inputLabel}
          aria-describedby={described || undefined}
          aria-invalid={invalid || problems.length > 0}
          onPick={(files) => {
            take(files, false);
          }}
        />
        <span className="pf-hint pf-file-drop">{t("file.drop")}</span>
      </div>
      {value.length > 0 ? (
        <ul className="pf-file-list" aria-label={t("file.list")}>
          {value.map((file, index) => (
            <li key={`${file.name}-${String(index)}`} className="pf-file-item">
              <span className="pf-file-name">{file.name}</span>
              <span className="pf-hint pf-num">{formatFileSize(file.size, i18n.language)}</span>
              <Button
                type="link"
                size="small"
                className="pf-file-remove"
                disabled={disabled}
                aria-label={t("file.removeItem", { name: file.name })}
                onClick={() => {
                  setProblems([]);
                  onChange(value.filter((_, other) => other !== index));
                }}
              >
                {t("file.remove")}
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
      {problems.length > 0 ? (
        <span className="pf-file-error" id={errorId} role="alert">
          {problems.join(" ")}
        </span>
      ) : null}
    </div>
  );
}
