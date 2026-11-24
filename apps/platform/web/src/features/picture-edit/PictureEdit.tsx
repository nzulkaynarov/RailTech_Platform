import { Alert } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../shared/api/errors";
import { CompanyAvatar, PersonAvatar } from "../../shared/ui/EntityCell";
import { FilePicker } from "../../shared/ui/FileField";
import { CloseIcon } from "../../shared/ui/lucide";
import { AvatarCropper } from "../profile/AvatarCropper";

import "./picture-edit.css";

const ACCEPTED = ["image/png", "image/jpeg", "image/webp"];

/** Текст отказа: подкод ERP (`details.reason`), затем код BFF, иначе общий текст. */
function errorKey(error: unknown): string {
  if (error instanceof ApiError) {
    const reason = error.details["reason"];
    if (typeof reason === "string" && reason) return reason;
    return error.code;
  }
  return "default";
}

/**
 * Логотип компании и фото контакта с загрузкой (ЕД-5, СУЩ-3). Картинка — кнопка: нажатие открывает выбор файла, затем
 * окно обрезки (квадрат для логотипа, круг для человека; в сеть уходит готовый 256×256), «Убрать» стоит рядом. Без права
 * править — просто картинка. Загрузку и удаление делает вызывающий (`onSave`, `onRemove` возвращают обещание): каким
 * запросом и что обновить после него, знает он.
 */
export function PictureEdit({
  kind,
  name,
  src,
  size = 40,
  editable,
  onSave,
  onRemove,
}: {
  kind: "company" | "person";
  name: string;
  src?: string | null;
  size?: 24 | 32 | 40 | 56;
  editable: boolean;
  onSave: (file: File) => Promise<unknown>;
  onRemove: () => Promise<unknown>;
}) {
  const { t } = useTranslation("clients");
  const [file, setFile] = useState<File | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const shape = kind === "company" ? "square" : "circle";
  const text = (key: string) => {
    const path = `picture.errors.${key}`;
    return t(path, { defaultValue: t("picture.errors.default") });
  };

  const label = t(src ? `picture.${kind}.change` : `picture.${kind}.choose`, { name });
  const picture =
    kind === "company" ? (
      <CompanyAvatar name={name} logoUrl={src} size={size} />
    ) : (
      <PersonAvatar name={name} photoUrl={src} size={size} />
    );
  if (!editable) return picture;

  const pick = (picked: File | undefined) => {
    if (!picked) return;
    if (!ACCEPTED.includes(picked.type)) {
      setError(text("file_type_not_allowed"));
      return;
    }
    setError(null);
    setFile(picked);
  };
  const save = (blob: Blob) => {
    setSaving(true);
    onSave(new File([blob], "picture.png", { type: "image/png" })).then(
      () => {
        setSaving(false);
        setFile(null);
      },
      (failure: unknown) => {
        setSaving(false);
        setError(text(errorKey(failure)));
      },
    );
  };
  const remove = () => {
    setError(null);
    onRemove().catch((failure: unknown) => {
      setError(text(errorKey(failure)));
    });
  };

  return (
    <span className="pf-picture-edit">
      <FilePicker
        accept={ACCEPTED.join(",")}
        inputLabel={t(`picture.${kind}.input`, { name })}
        onPick={(files) => {
          pick(files[0]);
        }}
        trigger={
          <button type="button" className="pf-picture-edit__pic pf-focusable" title={label}>
            {picture}
            <span className="pf-sr-only">{label}</span>
          </button>
        }
      />
      {src ? (
        <button
          type="button"
          className="pf-picture-edit__remove pf-focusable"
          aria-label={t(`picture.${kind}.remove`, { name })}
          title={t(`picture.${kind}.remove`, { name })}
          onClick={remove}
        >
          <CloseIcon />
        </button>
      ) : null}
      {error && !file ? (
        <Alert
          type="error"
          showIcon
          role="alert"
          message={error}
          className="pf-picture-edit__error"
        />
      ) : null}
      <AvatarCropper
        key={file ? `${file.name}-${String(file.lastModified)}-${String(file.size)}` : "none"}
        file={file}
        saving={saving}
        error={error}
        shape={shape}
        title={t(`picture.${kind}.cropTitle`)}
        hint={t(`picture.${kind}.cropHint`)}
        applyLabel={t(`picture.${kind}.apply`)}
        onCancel={() => {
          setFile(null);
          setError(null);
        }}
        onSave={save}
      />
    </span>
  );
}
