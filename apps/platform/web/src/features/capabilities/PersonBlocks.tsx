import { useTranslation } from "react-i18next";

import type {
  CapabilityAuthority,
  CapabilityZone,
  DeputyPeriod,
} from "../../shared/api/generated/model";
import { useFormat } from "../../shared/lib/useFormat";
import { MoneyText } from "../../shared/ui/MoneyText";
import { pickText } from "./model";
import { useKindNames } from "./useKindNames";

/** «Подписывает»: записи реестра прав подписи — виды документов, предел суммы, основание, срок. Реестр не прочитан — не «нет». */
export function SigningBlock({
  title,
  known,
  items,
}: {
  title: string;
  known: boolean;
  items: readonly CapabilityAuthority[];
}) {
  const { t } = useTranslation("capabilities");
  const format = useFormat();
  const kindName = useKindNames(known && items.length > 0);
  return (
    <div className="pf-cap-block" data-testid="cap-signing">
      <h4>{title}</h4>
      {!known ? (
        <p className="pf-hint">{t("card.signingUnknown")}</p>
      ) : items.length === 0 ? (
        <p className="pf-hint">{t("card.signingEmpty")}</p>
      ) : (
        <ul>
          {items.map((item) => (
            <li key={item.id}>
              {item.kinds.map(kindName).join(", ")}
              {" · "}
              {item.limit ? (
                <MoneyText value={item.limit.amount} currency={item.limit.currency} />
              ) : (
                t("matrix.unlimited")
              )}
              {item.valid_to
                ? ` · ${t("card.signingUntil", { date: format.date(item.valid_to) })}`
                : ""}
              {item.basis === "power_of_attorney" ? ` · ${t("card.signingPower")}` : ""}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** «Отвечает за»: области, где человек ответственный, замещающий или куратор. Зона пока справочная — задач не направляет. */
export function ZonesBlock({
  title,
  known,
  items,
}: {
  title: string;
  known: boolean;
  items: readonly CapabilityZone[];
}) {
  const { t, i18n } = useTranslation("capabilities");
  return (
    <div className="pf-cap-block" data-testid="cap-zones">
      <h4>{title}</h4>
      {!known ? (
        <p className="pf-hint">{t("card.responsibleUnknown")}</p>
      ) : items.length === 0 ? (
        <p className="pf-hint">{t("card.responsibleEmpty")}</p>
      ) : (
        <>
          <ul>
            {items.map((zone) => (
              <li key={`${zone.id}-${zone.role}`}>
                {pickText(zone.name, i18n.language)} · {t(`card.responsibleRole.${zone.role}`)}
              </li>
            ))}
          </ul>
          <p className="pf-hint">{t("card.responsibleNote")}</p>
        </>
      )}
    </div>
  );
}

/** «Замещение»: кто и когда замещает, что переходит и что нет. */
export function DeputyBlock({
  title,
  deputy,
  noneText,
}: {
  title: string;
  deputy: DeputyPeriod | undefined;
  noneText: string;
}) {
  const { t } = useTranslation("capabilities");
  const format = useFormat();
  return (
    <div className="pf-cap-block" data-testid="cap-deputy">
      <h4>{title}</h4>
      {deputy ? (
        <>
          <p style={{ margin: 0 }}>
            {t("card.deputyLine", {
              name: deputy.name,
              from: format.date(deputy.date_from),
              to: format.date(deputy.date_to),
            })}
          </p>
          <p className="pf-hint">{t("card.deputyPasses")}</p>
        </>
      ) : (
        <p className="pf-hint">{noneText}</p>
      )}
    </div>
  );
}
