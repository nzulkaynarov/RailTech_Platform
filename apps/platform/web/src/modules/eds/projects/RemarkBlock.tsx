import { Button, Input } from "antd";
import { type ReactNode, useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ProjectContractRemark } from "../../../shared/api/generated/model";
import { canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { settingByKey } from "../../admin/settingsRegistry";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { useFormat } from "../../../shared/lib/useFormat";
import { ErrorNote, FormField } from "../../../shared/ui/FormParts";
import { RegistryTable } from "../../../shared/ui/RegistryTable";

type Item = ProjectContractRemark["items"][number];

/** Слова пункта с подсветкой: слева удалённое, справа добавленное, общее — как есть. */
function Segments({ item, side }: { item: Item; side: "ours" | "theirs" }) {
  if (item.segments.length === 0) return <>{side === "ours" ? item.ours : item.theirs}</>;
  const own = side === "ours" ? "del" : "ins";
  const other = side === "ours" ? "ins" : "del";
  return (
    <>
      {item.segments
        .filter((s) => s.op !== other)
        .map((s, i) =>
          s.op === own ? (
            side === "ours" ? (
              <del key={i}>{s.text}</del>
            ) : (
              <ins key={i}>{s.text}</ins>
            )
          ) : (
            <span key={i}>{s.text}</span>
          ),
        )}
    </>
  );
}

type Send = (
  action: "remark_vote" | "remark_decide",
  extra: { approve: boolean; text?: string },
) => void;

/**
 * Замечания контрагента (ДП-1): комментарий, его редакция, что изменилось, ответы ответственных, их ответ («Согласен» /
 * «Не согласен») и решение директора при разногласии. Всё, включая права, считает ERP (`remark.actions`).
 */
export function RemarkBlock({
  remark,
  fileHref,
  busy,
  pending,
  error,
  send,
}: {
  remark: ProjectContractRemark;
  fileHref: ReactNode;
  busy: boolean;
  pending: string | null;
  error: string | null;
  send: Send;
}) {
  const { t } = useTranslation("projects");
  const { me } = useAuth();
  const org = settingByKey("org");
  const canOpenOrg = org !== undefined && canSee(me, org.access);
  const { date } = useFormat();
  const ids = { vote: useId(), counter: useId() };
  const [voteText, setVoteText] = useState("");
  const [counter, setCounter] = useState("");
  const [mode, setMode] = useState<"vote" | "counter" | null>(null);
  const [touched, setTouched] = useState(false);
  const summary = remark.summary;
  const parts = (["changed", "added", "removed"] as const)
    .filter((kind) => summary[kind].length > 0)
    .map((kind) => t(`contract.remark.summary.${kind}`, { points: summary[kind].join(", ") }));
  const may = (action: "vote" | "decide") => remark.actions.includes(action);
  const done = remark.votes.length;
  const total = done + remark.awaiting.length;

  return (
    <section
      className="pf-dec-brief"
      aria-label={t("contract.remark.title")}
      data-testid="contract-remark"
    >
      <h3 className="pf-ctpl-head" style={{ margin: 0 }}>
        {t("contract.remark.title")}
      </h3>
      <p className="pf-hint" style={{ margin: 0 }}>
        {t("contract.remark.from", {
          name: remark.author_name || t("contract.remark.counterparty"),
          edition: remark.edition,
          date: date(remark.received_at, "datetime"),
        })}
      </p>
      <p style={{ margin: 0 }}>{remark.comment}</p>
      {fileHref ? <div>{fileHref}</div> : null}

      {parts.length > 0 ? (
        <p style={{ margin: 0 }} data-testid="remark-summary">
          {parts.join("; ")}
          {(summary.more ?? 0) > 0
            ? `; ${t("contract.remark.summary.more", { count: summary.more })}`
            : ""}
        </p>
      ) : remark.has_file && !summary.comparable ? (
        <p className="pf-hint" style={{ margin: 0 }}>
          {t("contract.remark.noCompare")}
        </p>
      ) : null}

      {remark.items.length > 0 ? (
        <RegistryTable<Item>
          tableId="eds.contract-remark"
          caption={t("contract.remark.compare")}
          scrollLabel={t("contract.remark.compare")}
          flexMin={200}
          nested
          rows={remark.items}
          rowKey={(item) =>
            `${item.kind}-${item.point}-${item.ours.slice(0, 24)}-${item.theirs.slice(0, 24)}`
          }
          empty={null}
          columns={[
            {
              id: "point",
              header: t("contract.remark.col.point"),
              width: 110,
              hideable: false,
              cell: (item) => (
                <>
                  {item.point ? `${t("contract.remark.point")} ${item.point}` : "—"}
                  <br />
                  <span className="pf-hint">{t(`contract.remark.kind.${item.kind}`)}</span>
                </>
              ),
            },
            {
              id: "ours",
              header: t("contract.remark.col.ours"),
              width: null,
              cell: (item) =>
                item.kind === "changed" ? <Segments item={item} side="ours" /> : item.ours || "—",
            },
            {
              id: "theirs",
              header: t("contract.remark.col.theirs"),
              width: null,
              cell: (item) =>
                item.kind === "changed" ? (
                  <Segments item={item} side="theirs" />
                ) : (
                  item.theirs || "—"
                ),
            },
          ]}
        />
      ) : null}

      <h4 className="pf-ctpl-head" style={{ margin: 0 }}>
        {t("contract.remark.votes.title", { done, total })}
      </h4>
      <ul style={{ margin: 0, paddingInlineStart: 18 }}>
        {remark.votes.map((vote) => (
          <li key={vote.user.id}>
            <strong>{vote.user.name}</strong>{" "}
            {vote.agree ? t("contract.remark.votes.agree") : t("contract.remark.votes.disagree")}
            {vote.comment ? ` — ${vote.comment}` : ""}
          </li>
        ))}
        {remark.awaiting.map((person) => (
          <li key={person.id} className="pf-hint">
            {person.name} — {t("contract.remark.votes.waiting")}
          </li>
        ))}
      </ul>

      {may("vote") ? (
        <div className="pf-fp-form">
          <FormField
            id={ids.vote}
            label={t("contract.remark.vote.label")}
            hint={t("contract.remark.vote.hint")}
          >
            <Input.TextArea
              id={ids.vote}
              rows={2}
              maxLength={4000}
              value={voteText}
              aria-describedby={`${ids.vote}-hint`}
              onChange={(event) => {
                setVoteText(event.target.value);
              }}
            />
          </FormField>
          {touched && !voteText.trim() ? (
            <p className="pf-field-error" role="alert">
              {t("contract.remark.vote.needWords")}
            </p>
          ) : null}
          <div className="pf-fp-row">
            <Button
              type="primary"
              loading={pending === "remark_vote"}
              disabled={busy}
              onClick={() => {
                send("remark_vote", { approve: true, text: voteText.trim() });
              }}
            >
              {t("contract.remark.votes.agree")}
            </Button>
            <Button
              danger
              disabled={busy}
              onClick={() => {
                setTouched(true);
                if (voteText.trim()) send("remark_vote", { approve: false, text: voteText.trim() });
              }}
            >
              {t("contract.remark.votes.disagree")}
            </Button>
          </div>
        </div>
      ) : null}

      {
        <>
          {remark.deciders.length > 0 ? (
            <p className="pf-hint" style={{ margin: 0 }} data-testid="remark-deciders">
              {t("contract.remark.decide.who", {
                names: remark.deciders.map((p) => p.name).join(", "),
              })}
            </p>
          ) : (
            <div className="pf-hint" role="status" data-testid="remark-no-decider">
              <p style={{ margin: 0 }}>{t("contract.remark.decide.nobody")}</p>
              {canOpenOrg ? (
                <LinkButton size="small" to="/admin/org">
                  {t("contract.remark.decide.nobodyLink")}
                </LinkButton>
              ) : null}
            </div>
          )}
          {may("decide") ? (
            <div className="pf-fp-form">
              <div className="pf-fp-row">
                <Button
                  type="primary"
                  disabled={busy}
                  loading={pending === "remark_decide" && mode !== "counter"}
                  onClick={() => {
                    send("remark_decide", { approve: true });
                  }}
                >
                  {t("contract.remark.decide.accept")}
                </Button>
                <Button
                  disabled={busy}
                  onClick={() => {
                    setMode(mode === "counter" ? null : "counter");
                  }}
                >
                  {t("contract.remark.decide.counter")}
                </Button>
              </div>
              {mode === "counter" ? (
                <>
                  <FormField
                    id={ids.counter}
                    label={t("contract.remark.decide.counterLabel")}
                    hint={t("contract.remark.decide.counterHint")}
                  >
                    <Input.TextArea
                      id={ids.counter}
                      rows={3}
                      maxLength={4000}
                      value={counter}
                      aria-describedby={`${ids.counter}-hint`}
                      onChange={(event) => {
                        setCounter(event.target.value);
                      }}
                    />
                  </FormField>
                  <Button
                    type="primary"
                    disabled={busy || !counter.trim()}
                    loading={pending === "remark_decide"}
                    onClick={() => {
                      send("remark_decide", { approve: false, text: counter.trim() });
                    }}
                  >
                    {t("contract.remark.decide.send")}
                  </Button>
                </>
              ) : null}
            </div>
          ) : null}
        </>
      }
      <p className="pf-hint" style={{ margin: 0 }}>
        {t("contract.remark.next")}
      </p>
      <ErrorNote message={error} />
    </section>
  );
}
