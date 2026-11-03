import { keepPreviousData } from "@tanstack/react-query";
import { App, Card, Checkbox, Input, Segmented, Skeleton } from "antd";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { ApiError } from "../../../shared/api/errors";
import type { InboundMailItem } from "../../../shared/api/generated/model";
import { releaseInboundMail, useListInboundMail } from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { TabsBar } from "../../../shared/ui/TabsBar";
import { BulkBar } from "./BulkArchive";
import { MailRow } from "./MailRow";
import { MailView } from "./MailView";
import {
  ADMIN_MAIL_PATH,
  BULK_TABS,
  CLERK_TABS,
  type MailTab,
  OWN_TABS,
  tabCount,
  useRefreshMail,
} from "./mailModel";

import "../inbox/inbox.css";
import "./mail.css";

type Show = "all" | "history";
const SEARCH_DELAY_MS = 300;

/** Задержка поиска: запрос уходит, когда человек перестал печатать. */
function useDebounced(value: string): string {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSettled(value);
    }, SEARCH_DELAY_MS);
    return () => {
      window.clearTimeout(timer);
    };
  }, [value]);
  return settled;
}

function MailList({ own }: { own: boolean }) {
  const { t } = useTranslation(["letters", "modules"]);
  const { me } = useAuth();
  const { message } = App.useApp();
  const refresh = useRefreshMail();
  const [params, setParams] = useSearchParams();
  const tabs = own ? OWN_TABS : CLERK_TABS;
  const fallback: MailTab = own ? "mine" : "new";
  const asked = params.get("tab") as MailTab | null;
  const tab: MailTab = asked && tabs.includes(asked) ? asked : fallback;
  const show: Show = tab === "new" && params.get("show") === "history" ? "history" : "all";
  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim());
  const [picked, setPicked] = useState<readonly number[]>([]);
  const query = useListInboundMail(
    {
      view: tab,
      ...(show === "history" ? { history: true } : {}),
      ...(q ? { q } : {}),
    },
    { query: { placeholderData: keepPreviousData } },
  );
  const title = t("modules:eds.sections.mail");
  useDocumentTitle(title);
  const data = query.data;
  const canBulk = !own && BULK_TABS.includes(tab);
  const go = (next: { tab?: MailTab; show?: Show }) => {
    const nextTab = next.tab ?? tab;
    const nextShow = nextTab === "new" ? (next.show ?? (next.tab ? "all" : show)) : "all";
    const search = new URLSearchParams();
    if (nextTab !== fallback) search.set("tab", nextTab);
    if (nextShow === "history") search.set("show", "history");
    setParams(search, { replace: true });
    setPicked([]);
  };
  const giveBack = async (mail: InboundMailItem) => {
    try {
      await releaseInboundMail(mail.id);
      void message.success(t("letters:mail.returned"));
      await refresh();
    } catch (failure) {
      const reason = failure instanceof ApiError ? failure.message : String(failure);
      void message.error(t("letters:mail.actions.failed", { reason }));
    }
  };
  const caption = t(`letters:mail.caption.${tab}`);
  const label = (key: MailTab) => {
    const name = t(own && key === "all" ? "letters:mail.tabs.ownAll" : `letters:mail.tabs.${key}`);
    return data ? `${name} · ${String(tabCount(data.counts, key))}` : name;
  };
  const pageIds = data?.items.map((i) => i.id) ?? [];
  let body;
  if (query.isPending) {
    body = <Skeleton active paragraph={{ rows: 6 }} />;
  } else if (!data) {
    body = (
      <EmptyState
        title={t("letters:state.loadError.title")}
        text={t("letters:state.loadError.text")}
      />
    );
  } else if (!data.mailbox.configured && !own) {
    body = (
      <EmptyState
        title={t("letters:mail.off.title")}
        text={t("letters:mail.off.text")}
        action={
          canSee(me, { resource: "admin" }) ? (
            <LinkButton to={ADMIN_MAIL_PATH}>{t("letters:mail.off.action")}</LinkButton>
          ) : undefined
        }
      />
    );
  } else if (data.items.length === 0) {
    const empty = q ? "search" : show === "history" ? "history" : tab;
    body = (
      <EmptyState
        title={t(`letters:mail.empty.${empty}.title`)}
        text={t(`letters:mail.empty.${empty}.text`)}
      />
    );
  } else {
    body = (
      <ul className="pf-mail-list" aria-label={caption}>
        {data.items.map((mail) => (
          <MailRow
            key={mail.id}
            mail={mail}
            own={own}
            personalLabel={data.mailbox.personal_label}
            selected={canBulk ? picked.includes(mail.id) : undefined}
            onSelect={
              canBulk
                ? (checked) => {
                    setPicked((prev) =>
                      checked
                        ? [...new Set([...prev, mail.id])]
                        : prev.filter((i) => i !== mail.id),
                    );
                  }
                : undefined
            }
            onReturn={(item) => void giveBack(item)}
          />
        ))}
      </ul>
    );
  }
  return (
    <div className="pf-mail">
      <PageHeader title={title} subtitle={t("letters:mail.subtitle")} />
      <Card styles={{ body: { padding: 0 } }}>
        <TabsBar
          id="pf-mail-tabs"
          label={t("letters:mail.tabs.label")}
          activeKey={tab}
          onChange={(key) => {
            go({ tab: key as MailTab });
          }}
          tabBarStyle={{ margin: 0, padding: "0 16px" }}
          items={tabs.map((key) => ({ key, label: label(key) }))}
        >
          <div className="pf-mail-body">
            <div className="pf-mail-tools">
              <Input.Search
                allowClear
                className="pf-mail-search"
                aria-label={t("letters:mail.search.label")}
                placeholder={t("letters:mail.search.placeholder")}
                value={search}
                maxLength={100}
                onChange={(event) => {
                  setSearch(event.target.value);
                  setPicked([]);
                }}
              />
              {tab === "new" && !own ? (
                <Segmented<Show>
                  aria-label={t("letters:mail.filter.label")}
                  value={show}
                  onChange={(value) => {
                    go({ show: value });
                  }}
                  options={[
                    { value: "all", label: t("letters:mail.filter.all") },
                    {
                      value: "history",
                      label: data
                        ? `${t("letters:mail.filter.history")} · ${String(data.counts.history)}`
                        : t("letters:mail.filter.history"),
                    },
                  ]}
                />
              ) : null}
            </div>
            {tab === "spam" ? (
              <p className="pf-hint pf-mail-what">{t("letters:mail.spamIntro")}</p>
            ) : null}
            {canBulk && data && data.items.length > 0 ? (
              <div className="pf-mail-pick">
                <Checkbox
                  checked={picked.length > 0 && picked.length === pageIds.length}
                  indeterminate={picked.length > 0 && picked.length < pageIds.length}
                  onChange={(event) => {
                    setPicked(event.target.checked ? pageIds : []);
                  }}
                >
                  {t("letters:mail.bulk.all")}
                </Checkbox>
              </div>
            ) : null}
            {picked.length > 0 ? (
              <BulkBar
                ids={picked}
                onClear={() => {
                  setPicked([]);
                }}
              />
            ) : null}
            {body}
          </div>
        </TabsBar>
      </Card>
    </div>
  );
}

/**
 * Документы · Входящая почта (W18A-P2, W18A-P2-3): очередь `/eds/mail` или карточка `/eds/mail/:id` у первой линии; у
 * сотрудника без раздела первой линии (`own`) те же экраны по `/eds/my-mail` — только его письма.
 */
export function MailScreen({
  objectId,
  own = false,
}: {
  objectId?: string | undefined;
  own?: boolean;
}) {
  const id = Number(objectId);
  return objectId && Number.isInteger(id) && id > 0 ? (
    <MailView id={id} own={own} />
  ) : (
    <MailList own={own} />
  );
}
