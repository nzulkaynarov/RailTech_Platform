import { Drawer } from "antd";
import { type ReactNode, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { PanelPortal } from "../../../app/shell/PanelSlot";
import { useViewport } from "../../../app/shell/useViewport";
import type { LetterCard } from "../../../shared/api/generated/model";
import { useGetLetter } from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { QueryState } from "../../../shared/ui/FormParts";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { Attachments } from "./Parts";
import { letterPath, letterRef } from "./api";
import { clearDraft } from "./draft";
import { ResolutionForm } from "./ResolutionForm";
import { useStateLabels } from "./labels";

function Brief({ letter }: { letter: LetterCard }) {
  const { t } = useTranslation("letters");
  const { date } = useFormat();
  return (
    <section className="pf-res-brief" aria-label={letter.number}>
      <div className="pf-res-brief-head">
        <h3 className="pf-fp-title">{letter.number}</h3>
        <StatusTag kind="incoming" status={letter.status} />
      </div>
      <p className="pf-res-subject">{letter.subject}</p>
      <DefinitionList
        items={[
          { label: t("panel.brief.client"), value: letter.sender.name },
          { label: t("panel.brief.request"), value: letter.request?.number },
          { label: t("panel.brief.received"), value: date(letter.received_at) },
        ]}
      />
      <h4 className="pf-res-subhead">{t("panel.brief.summary")}</h4>
      <p className="pf-res-summary">{letter.summary}</p>
      {letter.files.length > 0 ? (
        <>
          <h4 className="pf-res-subhead">{t("panel.brief.files")}</h4>
          <Attachments files={letter.files} />
        </>
      ) : null}
      <Link className="pf-focusable pf-res-open" to={letterPath(letter.number)}>
        {t("panel.briefOpen")}
      </Link>
    </section>
  );
}

function PanelBody({
  letter,
  variant,
  brief,
  onDone,
}: {
  letter: LetterCard;
  variant: "panel" | "sheet";
  brief: boolean;
  onDone?: () => void;
}) {
  const { t } = useTranslation("letters");
  const { me } = useAuth();
  const canResolve = canEdit(me, "eds.inbox");
  // Письмо уже решено, возвращено или отклонено (в том числе другим): черновик ему не нужен.
  useEffect(() => {
    if (letter.status !== "awaiting_resolution") clearDraft(me.id, letter.id);
  }, [letter.status, letter.id, me.id]);
  let body: ReactNode;
  if (letter.status === "awaiting_resolution" && canResolve) {
    body = <ResolutionForm letter={letter} variant={variant} {...(onDone ? { onDone } : {})} />;
  } else if (letter.status === "awaiting_resolution") {
    body = (
      <EmptyState
        level={3}
        compact
        title={t("panel.awaitingReadOnly.title")}
        text={t("panel.awaitingReadOnly.text")}
      />
    );
  } else {
    body = (
      <EmptyState
        level={3}
        compact
        title={t("panel.decided.title")}
        text={t("panel.decided.text")}
      />
    );
  }
  return (
    <div className="pf-res-panel pf-letters">
      {brief ? <Brief letter={letter} /> : null}
      {body}
    </div>
  );
}

/** Содержимое вкладки «Резолюция»: письмо по `ref` (id или номер), форма для директора, пояснение остальным. */
export function ResolutionPanel({
  letterRef: ref,
  brief = false,
  variant = "panel",
  onDone,
}: {
  letterRef: string;
  brief?: boolean;
  variant?: "panel" | "sheet";
  onDone?: () => void;
}) {
  const query = useGetLetter(letterRef(ref));
  const labels = useStateLabels();
  return (
    <QueryState query={query} labels={labels} level={3} compact>
      {(letter) => (
        <PanelBody
          letter={letter}
          variant={variant}
          brief={brief}
          {...(onDone ? { onDone } : {})}
        />
      )}
    </QueryState>
  );
}

function SheetTitle({ letterRef: ref }: { letterRef: string }) {
  const { t } = useTranslation("letters");
  const query = useGetLetter(letterRef(ref));
  return (
    <>{query.data ? t("panel.sheetTitle", { number: query.data.number }) : t("panel.sheetLabel")}</>
  );
}

/**
 * Где живёт «Резолюция» письма. Широкий и средний экран — вкладка бокового окна каркаса. Телефон (< 768 px) — полноэкранный
 * лист с кнопками внизу (директор согласует с телефона, UX P0-4): открывается параметром `?sheet=resolution`; ссылки из
 * очереди и колокольчика с `panel=open` на телефоне переводятся в лист, чтобы рядом не открывалось окно каркаса.
 */
export function ResolutionSlot({
  letterRef: ref,
  brief = false,
}: {
  letterRef: string;
  brief?: boolean;
}) {
  const { t } = useTranslation("letters");
  const { mobile } = useViewport();
  const [params, setParams] = useSearchParams();
  const sheetOpen = params.get("sheet") === "resolution";
  const wantsPanel = params.get("panel") === "open";

  useEffect(() => {
    if (!mobile || !wantsPanel) return;
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("panel");
        next.set("sheet", "resolution");
        return next;
      },
      { replace: true },
    );
  }, [mobile, wantsPanel, setParams]);

  if (!mobile) {
    return (
      <PanelPortal tab="resolution">
        <ResolutionPanel letterRef={ref} brief={brief} />
      </PanelPortal>
    );
  }
  const close = () => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("sheet");
        return next;
      },
      { replace: true },
    );
  };
  return (
    <Drawer
      open={sheetOpen}
      onClose={close}
      placement="bottom"
      height="100%"
      destroyOnHidden
      title={<SheetTitle letterRef={ref} />}
      closeIcon={null}
      extra={
        <button type="button" className="pf-res-close pf-focusable" onClick={close}>
          {t("panel.sheetClose")}
        </button>
      }
      styles={{ body: { padding: 16 }, header: { padding: "12px 16px" } }}
      aria-label={t("panel.sheetLabel")}
      className="pf-res-sheet"
    >
      <ResolutionPanel letterRef={ref} brief={brief} variant="sheet" onDone={close} />
    </Drawer>
  );
}
