import { Button, Input, Modal } from "antd";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { PlusIcon } from "../../shared/ui/icons";
import { useAuth } from "../auth/useAuth";
import {
  CREATE_GROUPS,
  type CreateKind,
  countFrequent,
  createKindsFor,
  frequentKinds,
} from "./createKinds";
import { useViewport } from "./useViewport";

import "./create-window.css";

/**
 * Кнопка «Создать» и её окно (docs/product/NAVIGATION.md, план 2026-11-12 п. 0.1): три группы, у вида строка «что
 * получится»; пункт открывает форму; ещё не готовое приглушено и подписано, когда появится.
 */
export function CreateMenu({ block = false }: { block?: boolean }) {
  const { t } = useTranslation("shell");
  const { me } = useAuth();
  const [open, setOpen] = useState(false);
  const kinds = useMemo(() => createKindsFor(me), [me]);
  if (kinds.length === 0) return null;

  const trigger = block ? (
    <Button
      type="primary"
      block
      icon={<PlusIcon />}
      onClick={() => {
        setOpen(true);
      }}
    >
      {t("create.label")}
    </Button>
  ) : (
    <Button
      type="primary"
      icon={<PlusIcon />}
      aria-label={t("create.label")}
      title={t("create.label")}
      className="pf-rail-create"
      onClick={() => {
        setOpen(true);
      }}
    />
  );
  return (
    <>
      {trigger}
      {open ? (
        <CreateWindow
          kinds={kinds}
          onClose={() => {
            setOpen(false);
          }}
        />
      ) : null}
    </>
  );
}

function matches(kind: CreateKind, query: string, label: string, hint: string): boolean {
  if (!query) return true;
  return [label, hint, ...kind.keywords].some((word) => word.toLocaleLowerCase().includes(query));
}

function CreateWindow({ kinds, onClose }: { kinds: CreateKind[]; onClose: () => void }) {
  const { t } = useTranslation("shell");
  const { mobile } = useViewport();
  const [query, setQuery] = useState("");
  const q = query.trim().toLocaleLowerCase();
  const visible = kinds.filter((kind) =>
    matches(kind, q, t(`create.kinds.${kind.key}`), t(`create.hints.${kind.key}`)),
  );
  const frequent = q ? [] : frequentKinds(kinds);
  const opened = (kind: CreateKind) => {
    countFrequent(kind.key);
    onClose();
  };

  return (
    <Modal
      open
      title={t("create.title")}
      footer={null}
      onCancel={onClose}
      width={mobile ? "100%" : 680}
      style={mobile ? { top: 0, maxWidth: "100vw", margin: 0, paddingBottom: 0 } : { top: 56 }}
      rootClassName={mobile ? "pf-create pf-create--mobile" : "pf-create"}
      destroyOnHidden
    >
      <div className="pf-create-body">
        <Input.Search
          autoFocus
          allowClear
          aria-label={t("create.search")}
          placeholder={t("create.search")}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
          }}
        />
        {frequent.length > 0 ? (
          <div className="pf-create-frequent">
            <span className="pf-hint">{t("create.frequent")}</span>
            {frequent.map((kind) => (
              <Link
                key={kind.key}
                to={kind.to ?? "#"}
                className="pf-create-chip pf-focusable"
                onClick={() => {
                  opened(kind);
                }}
              >
                {t(`create.kinds.${kind.key}`)}
              </Link>
            ))}
          </div>
        ) : null}
        {visible.length === 0 ? <p className="pf-hint">{t("create.empty")}</p> : null}
        <div className="pf-create-groups">
          {CREATE_GROUPS.map((group) => {
            const items = visible.filter((kind) => kind.group === group);
            if (items.length === 0) return null;
            const heading = `pf-create-${group}`;
            return (
              <section key={group} aria-labelledby={heading} className="pf-create-group">
                <h3 id={heading} className="pf-create-group-title">
                  {t(`create.groups.${group}`)}
                </h3>
                <ul className="pf-create-list">
                  {items.map((kind) => (
                    <li key={kind.key}>
                      <KindRow kind={kind} onOpen={opened} />
                    </li>
                  ))}
                </ul>
              </section>
            );
          })}
        </div>
      </div>
    </Modal>
  );
}

function KindRow({ kind, onOpen }: { kind: CreateKind; onOpen: (kind: CreateKind) => void }) {
  const { t } = useTranslation("shell");
  const label = t(`create.kinds.${kind.key}`);
  const hint = t(`create.hints.${kind.key}`);
  if (kind.to === undefined) {
    return (
      <div className="pf-create-kind pf-create-kind--soon" aria-disabled="true">
        <span className="pf-create-kind-title">
          {label}
          <span className="pf-create-soon">{t(`create.${kind.soon ?? "soon"}`)}</span>
        </span>
        <span className="pf-create-kind-hint">{hint}</span>
      </div>
    );
  }
  return (
    <Link
      to={kind.to}
      className="pf-create-kind pf-focusable"
      onClick={() => {
        onOpen(kind);
      }}
    >
      <span className="pf-create-kind-title">{label}</span>
      <span className="pf-create-kind-hint">{hint}</span>
    </Link>
  );
}
