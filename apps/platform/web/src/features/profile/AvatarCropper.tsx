import { Alert, Button, Modal, Slider } from "antd";
import { type KeyboardEvent, type PointerEvent, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { renderCircle } from "./cropExport";
import {
  MAX_ZOOM,
  MIN_ZOOM,
  type Offset,
  baseScale,
  clampOffset,
  clampZoom,
  sourceRect,
} from "./cropMath";

const VIEW = 240;
const KEY_STEP = 12;

/**
 * Обрезка фото по кругу на клиенте (W15-H6): файл читается в браузере, сотрудник двигает картинку и выбирает масштаб,
 * в сеть уходит только готовый круг 256×256 (PNG). Исходный файл на сервер не попадает.
 */
export function AvatarCropper({
  file,
  saving,
  error,
  onCancel,
  onSave,
}: {
  file: File | null;
  saving: boolean;
  error: string | null;
  onCancel: () => void;
  onSave: (blob: Blob) => void;
}) {
  const { t } = useTranslation("profile");
  const [url, setUrl] = useState<string | null>(null);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const [failed, setFailed] = useState(false);
  const [zoom, setZoom] = useState(MIN_ZOOM);
  const [offset, setOffset] = useState<Offset>({ x: 0, y: 0 });
  const image = useRef<HTMLImageElement | null>(null);
  const drag = useRef<{ x: number; y: number; start: Offset } | null>(null);

  // Файл читается в браузере; новый файл — новый экземпляр компонента (`key` у вызывающего), поэтому сброса состояния нет.
  useEffect(() => {
    if (!file) return;
    let cancelled = false;
    const reader = new FileReader();
    reader.onload = () => {
      if (!cancelled && typeof reader.result === "string") setUrl(reader.result);
    };
    reader.onerror = () => {
      if (!cancelled) setFailed(true);
    };
    reader.readAsDataURL(file);
    return () => {
      cancelled = true;
      reader.abort();
    };
  }, [file]);

  const move = (next: Offset, z = zoom) => {
    if (size) setOffset(clampOffset(size.w, size.h, VIEW, z, next));
  };
  const scale = size ? baseScale(size.w, size.h, VIEW) * zoom : 1;

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { x: event.clientX, y: event.clientY, start: offset };
  };
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d) return;
    move({ x: d.start.x + event.clientX - d.x, y: d.start.y + event.clientY - d.y });
  };
  const onPointerUp = () => {
    drag.current = null;
  };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const delta: Record<string, Offset> = {
      ArrowLeft: { x: -KEY_STEP, y: 0 },
      ArrowRight: { x: KEY_STEP, y: 0 },
      ArrowUp: { x: 0, y: -KEY_STEP },
      ArrowDown: { x: 0, y: KEY_STEP },
    };
    const step = delta[event.key];
    if (!step) return;
    event.preventDefault();
    move({ x: offset.x + step.x, y: offset.y + step.y });
  };
  const changeZoom = (value: number) => {
    const next = clampZoom(value);
    setZoom(next);
    if (size) setOffset((o) => clampOffset(size.w, size.h, VIEW, next, o));
  };

  const save = () => {
    const el = image.current;
    if (!el || !size) return;
    void renderCircle(el, sourceRect(size.w, size.h, VIEW, zoom, offset)).then(onSave, () => {
      setFailed(true);
    });
  };

  return (
    <Modal
      open={file !== null}
      title={t("photo.cropTitle")}
      onCancel={onCancel}
      destroyOnHidden
      width={340}
      footer={[
        <Button key="cancel" onClick={onCancel}>
          {t("photo.cancel")}
        </Button>,
        <Button
          key="apply"
          type="primary"
          loading={saving}
          disabled={!size || failed}
          onClick={save}
        >
          {t("photo.apply")}
        </Button>,
      ]}
    >
      <p className="pf-hint" style={{ margin: "0 0 12px" }}>
        {t("photo.cropHint")}
      </p>
      {failed || error ? (
        <Alert
          type="error"
          showIcon
          role="alert"
          message={failed ? t("photo.readError") : error}
          style={{ marginBottom: 12 }}
        />
      ) : null}
      <div
        role="group"
        tabIndex={0}
        aria-label={t("photo.cropArea")}
        className="pf-focusable"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onKeyDown={onKeyDown}
        style={{
          width: VIEW,
          height: VIEW,
          margin: "0 auto",
          position: "relative",
          overflow: "hidden",
          borderRadius: "50%",
          background: "#f0f0f0",
          touchAction: "none",
          cursor: "grab",
          outlineOffset: 2,
        }}
      >
        {url ? (
          <img
            ref={image}
            src={url}
            alt=""
            draggable={false}
            onLoad={(event) => {
              const el = event.currentTarget;
              setSize({ w: el.naturalWidth, h: el.naturalHeight });
            }}
            onError={() => {
              setFailed(true);
            }}
            style={{
              position: "absolute",
              left: "50%",
              top: "50%",
              width: size ? size.w * scale : undefined,
              height: size ? size.h * scale : undefined,
              maxWidth: "none",
              transform: `translate(calc(-50% + ${String(offset.x)}px), calc(-50% + ${String(offset.y)}px))`,
              userSelect: "none",
            }}
          />
        ) : null}
      </div>
      <div style={{ marginTop: 16 }}>
        <div className="pf-hint" aria-hidden="true">
          {t("photo.zoom")}
        </div>
        <Slider
          min={MIN_ZOOM}
          max={MAX_ZOOM}
          step={0.05}
          value={zoom}
          onChange={changeZoom}
          tooltip={{ open: false }}
          ariaLabelForHandle={t("photo.zoom")}
        />
      </div>
    </Modal>
  );
}
