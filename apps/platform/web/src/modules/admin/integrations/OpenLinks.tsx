import { Button } from "antd";
import { useTranslation } from "react-i18next";

import type { ServiceConsoleKey } from "../../../shared/api/generated/model";
import { useListServiceConsoles } from "../../../shared/api/generated/platform-bff";
import type { ServiceLink } from "./serviceLinks";

/** Внешние кабинеты сервиса: ссылки в новой вкладке, без учётных данных (OPS-CONSOLE). */
export function ExternalLinks({ links }: { links: readonly ServiceLink[] }) {
  const { t } = useTranslation("integrations");
  if (links.length === 0) return null;
  return (
    <div className="pf-int-row" role="group" aria-label={t("links.groupAria")}>
      {links.map((link) => (
        <Button
          key={link.href}
          size="small"
          href={link.href}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={t("links.newTabAria", { name: t(`links.${link.label}`) })}
        >
          {t(`links.${link.label}`)}
        </Button>
      ))}
    </div>
  );
}

/**
 * «Открыть консоль» внутреннего сервиса — только администратору (`admin: full`) и только если консоль включена на
 * сервере (`GET /admin/consoles`). Вход в саму консоль — её собственный (ключ или пароль сервиса).
 */
export function ConsoleLink({
  console: key,
  editable,
}: {
  console: ServiceConsoleKey;
  editable: boolean;
}) {
  const { t } = useTranslation("integrations");
  const query = useListServiceConsoles({ query: { enabled: editable, staleTime: 60_000 } });
  const item = editable ? query.data?.items.find((c) => (c.key as string) === key) : undefined;
  if (!item) return null;
  const name = t(`consoles.${key}.name`);
  return (
    <div className="pf-int-row">
      <Button
        size="small"
        href={item.url}
        target="_blank"
        rel="noopener noreferrer"
        aria-label={t("consoles.openAria", { name })}
      >
        {t("consoles.open", { name })}
      </Button>
      <span className="pf-hint">{t("consoles.ownLogin")}</span>
    </div>
  );
}
