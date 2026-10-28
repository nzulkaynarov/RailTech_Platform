import { Button, Spin } from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ThreadAttachment, ThreadMessage } from "../../../shared/api/generated/model";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { getCrmThread, useGetCrmThread } from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DeliveryMark } from "./DeliveryMark";
import { type Entry, PAGE_SIZE, mergeThread } from "./logic";

function Attachment({ file }: { file: ThreadAttachment }) {
  const { t } = useTranslation("messages");
  if (!file.url)
    return (
      <span className="pf-msg-file pf-msg-file--missing">
        {t("thread.notStored", { name: file.name })}
      </span>
    );
  return (
    <a
      className="pf-msg-file"
      href={file.url}
      download={file.name}
      aria-label={t("thread.download", { name: file.name })}
    >
      {file.name}
    </a>
  );
}

/**
 * Файл клиента — «В заявку»: форма «Создать заявку» с этим файлом как письмом директору (BFF копирует вложение в EDS,
 * `POST /crm/request-files/from-message`). Только у файлов лида и только с правом создавать заявки.
 */
function ToRequest({
  lead,
  message,
  file,
}: {
  lead: string;
  message: number;
  file: ThreadAttachment;
}) {
  const { t } = useTranslation("messages");
  return (
    <LinkButton
      size="small"
      to={`/crm/leads?lead=${lead}&create=1&letter=${String(message)}-${String(file.index)}&panel=open&tab=card`}
      aria-label={t("thread.toRequestLabel", { name: file.name })}
    >
      {t("thread.toRequest")}
    </LinkButton>
  );
}

function Bubble({ entry, lead, canCreate }: { entry: Entry; lead: string; canCreate: boolean }) {
  const { t } = useTranslation("messages");
  const fmt = useFormat();
  if (entry.kind === "note") {
    const { note } = entry;
    return (
      <li className="pf-msg-item pf-msg-item--note">
        <div className="pf-msg-item-head">
          <span className="pf-msg-tag-note">{t("thread.noteTag")}</span>
          {note.author_name ? <span>{note.author_name}</span> : null}
          <time dateTime={note.created_at}>{fmt.activity(note.created_at)}</time>
        </div>
        <div className="pf-msg-bubble">{note.text}</div>
      </li>
    );
  }
  const { message } = entry;
  const author = message.author_name ?? t(`thread.authors.${message.author}`);
  return (
    <li className={`pf-msg-item pf-msg-item--${message.author}`}>
      <div className="pf-msg-item-head">
        <span className="pf-msg-author">{author}</span>
        <time dateTime={message.created_at}>{fmt.activity(message.created_at)}</time>
      </div>
      {message.text ? <div className="pf-msg-bubble">{message.text}</div> : null}
      <DeliveryMark message={message} />
      {message.attachments.length ? (
        <div className="pf-msg-files">
          {message.attachments.map((file) => (
            <span key={file.index} className="pf-msg-file-row">
              <Attachment file={file} />
              {canCreate && message.author === "lead" && file.url ? (
                <ToRequest lead={lead} message={message.id} file={file} />
              ) : null}
            </span>
          ))}
        </div>
      ) : null}
    </li>
  );
}

/**
 * Лента диалога: сообщения клиента, бота и менеджера с вложениями (скачивание — ссылкой BFF), заметки команды. Последняя
 * страница — запрос, который обновляет подсказка `messages` потока; более ранние страницы неизменны и хранятся здесь.
 */
export function Thread({
  lead,
  name,
  canCreate = false,
}: {
  lead: string;
  name: string;
  /** Право создавать заявки (`crm.clients: full`) — у файлов клиента кнопка «В заявку» */
  canCreate?: boolean;
}) {
  const { t } = useTranslation("messages");
  const latest = useGetCrmThread(lead, { limit: PAGE_SIZE });
  const [older, setOlder] = useState<ThreadMessage[]>([]);
  const [olderHasMore, setOlderHasMore] = useState<boolean | null>(null);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [olderFailed, setOlderFailed] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);
  const hasMore = olderHasMore ?? latest.data?.has_more ?? false;
  const entries = useMemo(
    () => mergeThread(older, latest.data, !hasMore),
    [older, latest.data, hasMore],
  );
  const lastId = latest.data?.items.at(-1)?.id;

  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lastId, latest.data?.notes.length]);

  const loadOlder = async () => {
    const first = entries.find(
      (e): e is Extract<Entry, { kind: "message" }> => e.kind === "message",
    );
    if (!first) return;
    setLoadingOlder(true);
    setOlderFailed(false);
    try {
      const page = await getCrmThread(lead, { before: first.message.id, limit: PAGE_SIZE });
      setOlder((prev) => [...page.items, ...prev]);
      setOlderHasMore(page.has_more);
    } catch {
      setOlderFailed(true);
    } finally {
      setLoadingOlder(false);
    }
  };

  return (
    <div
      className="pf-msg-scroll"
      ref={scroller}
      tabIndex={0}
      aria-label={t("thread.label", { name })}
      role="region"
    >
      {latest.isPending ? (
        <div className="pf-msg-center">
          <Spin />
        </div>
      ) : (
        <>
          {hasMore ? (
            <div className="pf-msg-older">
              <Button size="small" onClick={() => void loadOlder()} loading={loadingOlder}>
                {loadingOlder ? t("thread.loadingOlder") : t("thread.older")}
              </Button>
              {olderFailed ? (
                <p className="pf-msg-older-error" role="alert">
                  {t("thread.olderFailed")}
                </p>
              ) : null}
            </div>
          ) : null}
          {entries.length ? (
            <ol className="pf-msg-items">
              {entries.map((entry) => (
                <Bubble
                  key={
                    entry.kind === "message"
                      ? `m${String(entry.message.id)}`
                      : `n${String(entry.note.id)}`
                  }
                  entry={entry}
                  lead={lead}
                  canCreate={canCreate}
                />
              ))}
            </ol>
          ) : (
            <p className="pf-msg-center">{t("thread.empty")}</p>
          )}
        </>
      )}
    </div>
  );
}
