import { Card } from "antd";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router";

import { canEdit, canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import type { ReferenceKind } from "../../../shared/api/generated/model";
import { useListDictionaries } from "../../../shared/api/generated/platform-bff";
import { localName } from "../../eds/dictionaries";
import { CategoriesTab } from "../company/tabs/CategoriesTab";
import { ChargesTab } from "../company/tabs/ChargesTab";
import { REFERENCE_KINDS, ReferenceTab } from "../company/tabs/ReferenceTab";
import { DictionariesTab } from "../docflow/DictionariesTab";
import { BotSettingsSections } from "./BotSettingsSections";
import { type NavGroup, SettingsNav } from "./SettingsNav";
import { SettingsPage } from "./SettingsPage";

import "../bot/bot.css";
import "../company/company.css";
import "../docflow/docflow.css";

/** Ключ справочника документооборота в `?list=`: `doc:<kind>` — у каталога BFF свои виды. */
const DOC_PREFIX = "doc:";

/**
 * Процессы · Справочники (SET-IA; ресёрч «Настройки» §4.3): все списки компании на одном экране, слева — по разделам.
 * Продажи — причины отказа и валюта сделок (раздел `deals` настроек бота); Документы — справочники писем (каталог BFF);
 * Расчёт — страны, валюты, единицы, базисы поставки, категории каталога и статьи расхода (нужен `company.settings`).
 * Данные не переносятся: каждый список хранит прежняя часть платформы (этап 2 — общий ресурс справочников, BACKLOG).
 */
export function DictionariesPage() {
  const { t, i18n } = useTranslation(["modules", "company", "bot"]);
  const { me } = useAuth();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const withAdmin = canSee(me, { resource: "admin" });
  const catalog = useListDictionaries({ query: { staleTime: 5 * 60_000, enabled: withAdmin } });
  const withCalc = canSee(me, { resource: "company.settings" });

  const groups: NavGroup[] = [
    {
      key: "sales",
      label: t("modules:admin.dictionaries.sales"),
      items: withAdmin ? [{ key: "deals", label: t("bot:keys.deals") }] : [],
    },
    {
      key: "documents",
      label: t("modules:admin.dictionaries.documents"),
      items: (catalog.data?.items ?? []).map((d) => ({
        key: `${DOC_PREFIX}${d.kind}`,
        label: localName(d.name, i18n.language),
      })),
    },
    ...(withCalc
      ? [
          {
            key: "calc",
            label: t("modules:admin.dictionaries.calc"),
            items: [
              ...REFERENCE_KINDS.map((kind) => ({
                key: kind,
                label: t(`company:reference.kinds.${kind}`),
              })),
              { key: "categories", label: t("company:tabs.categories") },
              { key: "charges", label: t("company:tabs.charges") },
            ],
          },
        ]
      : []),
  ].filter((group) => group.items.length > 0);

  const all = groups.flatMap((group) => group.items.map((item) => item.key));
  const asked = params.get("list");
  // `?list=doc` (старый адрес «Документооборот · Справочники») — первый справочник писем.
  const firstDoc = all.find((key) => key.startsWith(DOC_PREFIX));
  const current =
    asked && all.includes(asked)
      ? asked
      : asked === "doc" && firstDoc
        ? firstDoc
        : (all[0] ?? "deals");
  const hrefOf = (key: string) => `?${new URLSearchParams({ list: key }).toString()}`;

  let body;
  if (current === "deals") {
    body = <BotSettingsSections page="dictionaries" />;
  } else if (current.startsWith(DOC_PREFIX)) {
    body = (
      <Card styles={{ body: { padding: 0 } }}>
        <DictionariesTab readOnly={!canEdit(me, "admin")} kind={current.slice(DOC_PREFIX.length)} />
      </Card>
    );
  } else if (current === "categories") {
    body = (
      <Card styles={{ body: { padding: 0 } }}>
        <CategoriesTab />
      </Card>
    );
  } else if (current === "charges") {
    body = (
      <Card styles={{ body: { padding: 0 } }}>
        <ChargesTab />
      </Card>
    );
  } else {
    body = (
      <Card styles={{ body: { padding: 0 } }}>
        <ReferenceTab kind={current as ReferenceKind} />
      </Card>
    );
  }

  return (
    <SettingsPage sectionKey="dictionaries">
      <div className="pf-bot-layout">
        <SettingsNav
          label={t("modules:admin.dictionaries.nav")}
          groups={groups}
          current={current}
          hrefOf={hrefOf}
          onSelect={(key) => {
            void navigate({ search: hrefOf(key) });
          }}
        />
        <div className="pf-bot-content">{body}</div>
      </div>
    </SettingsPage>
  );
}
