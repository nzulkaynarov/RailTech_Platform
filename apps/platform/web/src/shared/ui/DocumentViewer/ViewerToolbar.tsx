import { Button, Input, InputNumber, Segmented } from "antd";
import { useTranslation } from "react-i18next";

import {
  AddIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  DownloadIcon,
  ExpandIcon,
  RemoveIcon,
  SearchIcon,
  ShrinkIcon,
} from "../lucide";
import type { ViewerApi } from "./types";

/**
 * Панель инструментов просмотра: одна и в одном порядке в панели и на весь экран — «По ширине | 100 %», масштаб,
 * страница, поиск, «Скачать», «На весь экран» / «Свернуть». В панели на телефоне масштаб и поиск убраны (слой на весь
 * экран открывается нажатием), на весь экран «Скачать» — главная кнопка.
 */
export function ViewerToolbar({
  api,
  mode,
  phone,
  onDownload,
  onFull,
  onClose,
}: {
  api: ViewerApi;
  mode: "panel" | "full";
  phone: boolean;
  onDownload: () => void;
  onFull?: () => void;
  onClose?: () => void;
}) {
  const { t } = useTranslation("ui");
  const ready = api.status === "ready";
  const compact = mode === "panel" && phone;
  const search = api.search;
  const total = search?.total ?? 0;
  return (
    <div
      className="pf-dv-toolbar"
      role="toolbar"
      aria-label={t("documentViewer.toolbar")}
      data-mode={mode}
    >
      {compact ? null : (
        <>
          <Segmented<string>
            size="small"
            aria-label={t("documentViewer.scaleMode")}
            value={api.fitted ? "fit" : api.percent === 100 ? "actual" : ""}
            onChange={(value) => {
              if (value === "fit") api.fit();
              else api.actual();
            }}
            options={[
              { value: "fit", label: t("documentViewer.fit"), disabled: !ready },
              { value: "actual", label: t("documentViewer.actual"), disabled: !ready },
            ]}
          />
          <div className="pf-dv-group">
            <Button
              size="small"
              type="text"
              disabled={!ready}
              aria-label={t("documentViewer.zoomOut")}
              icon={<RemoveIcon />}
              onClick={api.zoomOut}
            />
            <span className="pf-dv-percent" aria-live="polite">
              {api.percent} %
            </span>
            <Button
              size="small"
              type="text"
              disabled={!ready}
              aria-label={t("documentViewer.zoomIn")}
              icon={<AddIcon />}
              onClick={api.zoomIn}
            />
          </div>
        </>
      )}
      <div className="pf-dv-group">
        <InputNumber
          size="small"
          className="pf-dv-page"
          min={1}
          max={Math.max(1, api.pages)}
          controls={false}
          disabled={!ready || api.pages < 2}
          aria-label={t("documentViewer.page")}
          value={api.page}
          onChange={(value) => {
            if (typeof value === "number") api.goTo(value);
          }}
        />
        <span>{t("documentViewer.pageOf", { total: api.pages })}</span>
      </div>
      {search && !compact ? (
        <div className="pf-dv-search" role="search">
          <Input
            size="small"
            allowClear
            disabled={!ready}
            prefix={<SearchIcon />}
            placeholder={t("documentViewer.searchPlaceholder")}
            aria-label={t("documentViewer.search")}
            value={search.query}
            onChange={(event) => {
              search.find(event.target.value);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                if (event.shiftKey) search.prev();
                else search.next();
              } else if (event.key === "Escape" && search.query) {
                // первый Esc очищает поиск, слой закрывается вторым
                event.stopPropagation();
                search.clear();
              }
            }}
          />
          <span className="pf-dv-count" role="status" aria-live="polite">
            {search.query
              ? total > 0
                ? t("documentViewer.matches", { current: search.current, total })
                : t("documentViewer.noMatches")
              : ""}
          </span>
          <Button
            size="small"
            type="text"
            disabled={total === 0}
            aria-label={t("documentViewer.prevMatch")}
            icon={<ChevronUpIcon />}
            onClick={search.prev}
          />
          <Button
            size="small"
            type="text"
            disabled={total === 0}
            aria-label={t("documentViewer.nextMatch")}
            icon={<ChevronDownIcon />}
            onClick={search.next}
          />
        </div>
      ) : null}
      <div className="pf-dv-actions">
        <Button
          size={mode === "full" ? "middle" : "small"}
          type={mode === "full" ? "primary" : "default"}
          icon={<DownloadIcon />}
          onClick={onDownload}
        >
          {t("documentViewer.download")}
        </Button>
        {mode === "panel" && onFull ? (
          <Button size="small" icon={<ExpandIcon />} onClick={onFull} data-testid="dv-full">
            {t("documentViewer.full")}
          </Button>
        ) : null}
        {mode === "full" && onClose ? (
          <Button icon={<ShrinkIcon />} onClick={onClose} data-testid="dv-collapse">
            {t("documentViewer.collapse")} <kbd className="pf-dv-kbd">Esc</kbd>
          </Button>
        ) : null}
      </div>
    </div>
  );
}
