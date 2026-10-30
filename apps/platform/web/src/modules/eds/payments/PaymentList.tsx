import { useInfiniteQuery } from "@tanstack/react-query";
import { Button, Card, Input, Segmented } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { ApiError } from "../../../shared/api/errors";
import type { PaymentMemoStatus } from "../../../shared/api/generated/model";
import {
  getListPaymentMemosQueryKey,
  getListPaymentsQueryKey,
  listPaymentMemos,
  listPayments,
} from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { useLastDefined, useShownKey } from "../../../shared/lib/useShownKey";
import { DataBlock, ListSkeleton } from "../../../shared/ui/DataBlock";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { withParams } from "../inbox/api";
import { InvoiceRows } from "./InvoiceRows";
import { MemoRows } from "./MemoRows";
import { MemoSlot } from "./MemoPanel";
import { PaymentSlot } from "./PaymentPanel";
import { TabNav } from "./TabNav";
import { useStateLabels } from "./labels";
import { type InvoiceTab, PAGE, showTab } from "./model";

/** Куда ведёт кнопка пустого состояния вкладки (SPEC-v3 §7: пустое состояние — словами и с действием). */
const NEXT: Record<InvoiceTab, InvoiceTab | null> = {
  to_issue: "awaiting",
  awaiting: "proofs",
  proofs: "awaiting",
  overdue: "awaiting",
  all: null,
};

function errorState(
  error: unknown,
  labels: ReturnType<typeof useStateLabels>,
  erpText: { title: string; text: string },
) {
  if (error instanceof ApiError && error.status === 403) {
    if (error.source === "erp") return { ...erpText, retry: false };
    if (error.details["reason"] === "eds_not_granted") return { ...labels.forbidden, retry: false };
    return { ...labels.forbidden, retry: false };
  }
  if (error instanceof ApiError && error.status >= 500)
    return { ...labels.unavailable, retry: true };
  return { ...labels.loadError, retry: true };
}

/**
 * EDS · Счета и оплаты (SPEC-v3 §7.3): вкладки «К выставлению», «Ждут оплаты», «Платёжки на подтверждение», «Просрочены»,
 * «Служебки к оплате» и «Все счета»; таблица счетов с поиском; счёт и служебка открываются в боковом окне «Оплата».
 */
export function PaymentList() {
  const { t } = useTranslation(["payments", "modules"]);
  const [params, setParams] = useSearchParams();
  const labels = useStateLabels();
  const tab = showTab(params.get("show"));
  const query = (params.get("q") ?? "").trim();
  const memoStatus: PaymentMemoStatus = params.get("kind") === "paid" ? "paid" : "to_pay";
  const selectedPayment = params.get("payment");
  const selectedMemo = params.get("memo");
  const title = t("modules:eds.sections.payments");
  useDocumentTitle(title);

  // Поле поиска следует за адресом (переход по вкладке или «Сбросить поиск» очищает его): синхронизация без эффекта.
  const [draft, setDraft] = useState(query);
  const [seen, setSeen] = useState(query);
  if (seen !== query) {
    setSeen(query);
    setDraft(query);
  }

  const invoiceTab: InvoiceTab = tab === "memos" ? "awaiting" : tab;
  const boardParams = {
    tab: invoiceTab,
    ...(query && tab !== "memos" ? { q: query } : {}),
    limit: tab === "memos" ? 1 : PAGE,
  };
  const boardKey = getListPaymentsQueryKey(boardParams);
  const board = useInfiniteQuery({
    queryKey: boardKey,
    queryFn: ({ pageParam }) => listPayments({ ...boardParams, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((total, page) => total + page.items.length, 0);
      return loaded < last.count ? loaded : undefined;
    },
    // Прежние строки — только от списка счетов: на вкладке служебок тот же запрос идёт за одним счётом (ради чисел
    // вкладок), и его строка не должна мелькнуть вместо списка (UX-1c, S8)
    placeholderData: (previous, previousQuery) =>
      previousQuery?.queryKey[0] === boardKey[0] && previousQuery.queryKey[1]?.limit === PAGE
        ? previous
        : undefined,
  });
  const memoParams = { status: memoStatus, limit: PAGE };
  const memos = useInfiniteQuery({
    queryKey: getListPaymentMemosQueryKey(memoParams),
    queryFn: ({ pageParam }) =>
      listPaymentMemos({ ...memoParams, ...(pageParam ? { cursor: pageParam } : {}) }),
    initialPageParam: "",
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    enabled: tab === "memos",
  });

  const first = board.data?.pages[0];
  const invoices = board.data?.pages.flatMap((page) => page.items) ?? [];
  const memoRows = memos.data?.pages.flatMap((page) => page.items) ?? [];

  const go = (changes: Record<string, string | null>) => {
    setParams((prev) => new URLSearchParams(withParams(prev, changes).slice(1)), { replace: true });
  };
  const erpText = {
    title: t("payments:state.erpForbidden.title"),
    text: t("payments:state.erpForbidden.text"),
  };

  const memosTab = tab === "memos";
  const shownKey = useShownKey(
    memosTab ? getListPaymentMemosQueryKey(memoParams) : getListPaymentsQueryKey(boardParams),
    memosTab ? memos.isPlaceholderData : board.isPlaceholderData,
  );
  let body;
  if (tab === "memos") {
    if (memos.isPending) {
      body = <ListSkeleton rows={PAGE} />;
    } else if (memos.isError) {
      const state = errorState(memos.error, labels, erpText);
      body = (
        <EmptyState
          title={state.title}
          text={state.text}
          action={
            state.retry ? (
              <Button
                onClick={() => {
                  void memos.refetch();
                }}
              >
                {labels.retry}
              </Button>
            ) : undefined
          }
        />
      );
    } else if (memoRows.length === 0) {
      body = (
        <EmptyState
          title={t(`payments:memo.empty.${memoStatus}.title`)}
          text={t(`payments:memo.empty.${memoStatus}.text`)}
          action={
            <Button
              onClick={() => {
                go({ kind: memoStatus === "to_pay" ? "paid" : null, memo: null });
              }}
            >
              {t(`payments:memo.empty.${memoStatus}.action`)}
            </Button>
          }
        />
      );
    } else {
      body = (
        <>
          <MemoRows items={memoRows} selected={selectedMemo} />
          {memos.hasNextPage ? (
            <div className="pf-dec-pager">
              <Button
                loading={memos.isFetchingNextPage}
                onClick={() => {
                  void memos.fetchNextPage();
                }}
              >
                {t("payments:list.more")}
              </Button>
            </div>
          ) : null}
        </>
      );
    }
  } else if (board.isPending) {
    body = <ListSkeleton rows={PAGE} />;
  } else if (board.isError) {
    const state = errorState(board.error, labels, erpText);
    body = (
      <EmptyState
        title={state.title}
        text={state.text}
        action={
          state.retry ? (
            <Button
              onClick={() => {
                void board.refetch();
              }}
            >
              {labels.retry}
            </Button>
          ) : undefined
        }
      />
    );
  } else if (invoices.length === 0) {
    const searching = query !== "";
    const key = searching ? "search" : tab;
    const next = searching ? null : NEXT[tab];
    body = (
      <EmptyState
        title={t(`payments:list.empty.${key}.title`)}
        text={t(`payments:list.empty.${key}.text`)}
        action={
          <Button
            onClick={() => {
              if (searching) go({ q: null });
              else if (next) go({ show: next });
              else void board.refetch();
            }}
          >
            {t(`payments:list.empty.${key}.action`)}
          </Button>
        }
      />
    );
  } else {
    body = (
      <>
        <InvoiceRows items={invoices} selected={selectedPayment} />
        {board.hasNextPage ? (
          <div className="pf-dec-pager">
            <Button
              loading={board.isFetchingNextPage}
              onClick={() => {
                void board.fetchNextPage();
              }}
            >
              {t("payments:list.more")}
            </Button>
          </div>
        ) : null}
      </>
    );
  }

  // Числа вкладок — последние известные, пока счета перечитываются с другой вкладкой (UX-1c, S8)
  const knownCounts = useLastDefined(first?.counts);
  const knownMemos = useLastDefined(first ? first.memos_to_pay : undefined);
  const counts = board.isError ? undefined : knownCounts;
  const memosToPay = board.isError ? undefined : knownMemos;

  return (
    <div className="pf-dec-page">
      <PageHeader title={title} subtitle={t("payments:list.subtitle")} />
      <TabNav active={tab} counts={counts} memos={memosToPay} />
      {tab === "memos" ? (
        <Segmented
          aria-label={t("payments:memo.scope.label")}
          value={memoStatus}
          options={[
            { value: "to_pay", label: t("payments:memo.scope.to_pay") },
            { value: "paid", label: t("payments:memo.scope.paid") },
          ]}
          onChange={(value) => {
            go({ kind: value === "paid" ? "paid" : null, memo: null, sheet: null });
          }}
        />
      ) : (
        <div className="pf-pay-toolbar">
          <Input
            className="pf-pay-search"
            value={draft}
            allowClear
            aria-label={t("payments:list.search.label")}
            placeholder={t("payments:list.search.placeholder")}
            onChange={(event) => {
              setDraft(event.target.value);
              if (event.target.value === "" && query !== "") go({ q: null });
            }}
            onPressEnter={() => {
              const text = draft.trim();
              go({ q: text === "" ? null : text, payment: null });
            }}
          />
        </div>
      )}
      <Card styles={{ body: { padding: 0 } }}>
        <DataBlock
          busy={memosTab ? memos.isPlaceholderData : board.isPlaceholderData}
          resetKey={shownKey}
        >
          {body}
        </DataBlock>
      </Card>
      {tab !== "memos" && selectedPayment && /^\d+$/.test(selectedPayment) ? (
        <PaymentSlot invoiceId={Number(selectedPayment)} brief />
      ) : null}
      {tab === "memos" && selectedMemo ? <MemoSlot memoId={selectedMemo} brief /> : null}
    </div>
  );
}
