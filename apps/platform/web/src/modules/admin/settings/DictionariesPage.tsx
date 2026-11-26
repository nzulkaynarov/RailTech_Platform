import { Alert, Card } from "antd";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router";

import { canEdit, canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { useListDictionaries } from "../../../shared/api/generated/platform-bff";
import { localName } from "../../eds/dictionaries";
import { CategoriesTab } from "../company/tabs/CategoriesTab";
import { ChargesTab } from "../company/tabs/ChargesTab";
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
 * Процессы · Справочники (SET-IA; ресёрч «Настройки» §4.3): все списки компании на одном экране, выбор по разделам — над списком.
 * Продажи — причины отказа и валюта сделок (раздел `deals` настроек бота); Документы — справочники писем (каталог BFF);
 * «Типы входящих писем» и правила отправителей — настройки канала, они на странице «Почта» (ЕВ-2а);
 * Расчёт — страны, валюты, единицы, базисы поставки, категории каталога и статьи расхода (нужен `company.settings`).
 * Справочники всех доменов — общим ресурсом BFF `/dictionaries` (решение владельца 2026-11-11), в том числе «Расчёт» ERP.
 */
export function DictionariesPage() {
  const { t, i18n } = useTranslation(["modules", "company", "bot"]);
  const { me } = useAuth();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const withAdmin = canSee(me, { resource: "admin" });
  const withCalc = canSee(me, { resource: "company.settings" });
  // Каталог BFF сам оставляет справочники, которые сотруднику положено читать (решение 2026-11-11).
  const catalog = useListDictionaries({
    query: { staleTime: 5 * 60_000, enabled: withAdmin || withCalc },
  });

  const groups: NavGroup[] = [
    {
      key: "sales",
      label: t("modules:admin.dictionaries.sales"),
      items: withAdmin ? [{ key: "deals", label: t("bot:keys.deals") }] : [],
    },
    {
      key: "documents",
      label: t("modules:admin.dictionaries.documents"),
      items: (catalog.data?.items ?? [])
        .filter((d) => d.area === "documents")
        .map((d) => ({ key: `${DOC_PREFIX}${d.kind}`, label: localName(d.name, i18n.language) })),
    },
    ...(withCalc
      ? [
          {
            key: "calc",
            label: t("modules:admin.dictionaries.calc"),
            items: [
              ...(catalog.data?.items ?? [])
                // Категории — деревом на своей вкладке ниже; файлом их выгружает и загружает она же (план 3.8).
                .filter((d) => d.area === "calc" && d.kind !== "categories")
                .map((d) => ({
                  key: `${DOC_PREFIX}${d.kind}`,
                  label: localName(d.name, i18n.language),
                })),
              { key: "categories", label: t("company:tabs.categories") },
              { key: "charges", label: t("company:tabs.charges") },
            ],
          },
        ]
      : []),
  ].filter((group) => group.items.length > 0);

  const all = groups.flatMap((group) => group.items.map((item) => item.key));
  // Старые адреса «Расчёта» (`?list=currencies`) — тот же справочник на общем ресурсе.
  const rawList = params.get("list");
  const asked =
    rawList && all.includes(`${DOC_PREFIX}${rawList}`) ? `${DOC_PREFIX}${rawList}` : rawList;
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
  // Плашка «Только просмотр» — по открытому списку: «Расчёт» правит и держатель настроек компании.
  let editable = canEdit(me, "admin");
  if (current === "deals") {
    body = <BotSettingsSections page="dictionaries" />;
  } else if (current.startsWith(DOC_PREFIX)) {
    const kind = current.slice(DOC_PREFIX.length);
    const area = catalog.data?.items.find((d) => d.kind === kind)?.area;
    // «Расчёт» правит и держатель настроек компании — как раньше (решение 2026-11-11)
    editable = editable || (area === "calc" && canEdit(me, "company.settings"));
    body = (
      <>
        <Card styles={{ body: { padding: 0 } }}>
          <DictionariesTab readOnly={!editable} kind={kind} />
        </Card>
      </>
    );
  } else if (current === "categories") {
    editable = canEdit(me, "company.settings");
    body = (
      <Card styles={{ body: { padding: 0 } }}>
        <CategoriesTab />
      </Card>
    );
  } else if (current === "charges") {
    editable = canEdit(me, "company.settings");
    body = (
      <Card styles={{ body: { padding: 0 } }}>
        <ChargesTab />
      </Card>
    );
  } else {
    body = null;
  }

  const unavailable = catalog.data?.unavailable ?? [];
  return (
    <SettingsPage sectionKey="dictionaries" editable={editable}>
      {unavailable.length > 0 ? (
        <Alert
          type="warning"
          showIcon
          role="status"
          style={{ marginBottom: 16 }}
          message={t("modules:admin.dictionaries.partial", {
            lists: unavailable.map((d) => t(`modules:admin.dictionaries.domain.${d}`)).join(", "),
          })}
        />
      ) : null}
      <div className="pf-bot-content">
        <SettingsNav
          label={t("modules:admin.dictionaries.nav")}
          groups={groups}
          current={current}
          onSelect={(key) => {
            void navigate({ search: hrefOf(key) });
          }}
        />
        {body}
      </div>
    </SettingsPage>
  );
}
