/**
 * Известные нарушения «человеческого текста» (`humanText.ts`), которые НЕ входят в находки СЦ-7 и ждут своего PR или
 * инбокса плана. Запись снимает ровно одно совпадение в тестах одного файла; пустой список — идеал.
 * Новая запись — только с причиной и строкой в «Хвосты» PR.
 */

export interface AllowedHumanText {
  /** Фрагмент пути тестового файла, где нарушение допустимо */
  file: string;
  kind: "key" | "iso-date" | "bare-amount" | "plural-hack" | "internal-number";
  /** Точный найденный фрагмент */
  text: string;
  /** Почему допустимо и куда передано */
  reason: string;
}

export const ALLOWED_HUMAN_TEXT: readonly AllowedHumanText[] = [
  {
    file: "BusJournalPage.test",
    kind: "key",
    text: "crm.client.updated",
    reason:
      "технический журнал шины для администратора: код типа события — его суть; вынос в «Хвосты» PR СЦ-7",
  },
  {
    file: "BusJournalPage.test",
    kind: "key",
    text: "crm.contact.created",
    reason:
      "технический журнал шины для администратора: код типа события — его суть; вынос в «Хвосты» PR СЦ-7",
  },
  {
    file: "BusJournalPage.test",
    kind: "key",
    text: "crm.lead.created",
    reason:
      "технический журнал шины для администратора: код типа события — его суть; вынос в «Хвосты» PR СЦ-7",
  },
  {
    file: "BusJournalPage.test",
    kind: "key",
    text: "eds.approval.decided",
    reason:
      "технический журнал шины для администратора: код типа события — его суть; вынос в «Хвосты» PR СЦ-7",
  },
  {
    file: "BusJournalPage.test",
    kind: "key",
    text: "eds.letter.resolved",
    reason:
      "технический журнал шины для администратора: код типа события — его суть; вынос в «Хвосты» PR СЦ-7",
  },
  {
    file: "BusJournalPage.test",
    kind: "key",
    text: "erp.deal.stage_changed",
    reason:
      "технический журнал шины для администратора: код типа события — его суть; вынос в «Хвосты» PR СЦ-7",
  },
  {
    file: "BusJournalPage.test",
    kind: "key",
    text: "erp.deal.won",
    reason:
      "технический журнал шины для администратора: код типа события — его суть; вынос в «Хвосты» PR СЦ-7",
  },
  {
    file: "BusJournalPage.test",
    kind: "key",
    text: "erp.invoice.issued",
    reason:
      "технический журнал шины для администратора: код типа события — его суть; вынос в «Хвосты» PR СЦ-7",
  },
  {
    file: "BusJournalPage.test",
    kind: "key",
    text: "erp.quote.sent",
    reason:
      "технический журнал шины для администратора: код типа события — его суть; вынос в «Хвосты» PR СЦ-7",
  },
  {
    file: "BusJournalPage.test",
    kind: "key",
    text: "erp.request.created",
    reason:
      "технический журнал шины для администратора: код типа события — его суть; вынос в «Хвосты» PR СЦ-7",
  },
  {
    file: "BusJournalPage.test",
    kind: "key",
    text: "identity.user.updated",
    reason:
      "технический журнал шины для администратора: код типа события — его суть; вынос в «Хвосты» PR СЦ-7",
  },
  {
    file: "BusJournalPage.test",
    kind: "key",
    text: "payload.amount",
    reason:
      "технический журнал шины для администратора: код типа события — его суть; вынос в «Хвосты» PR СЦ-7",
  },
  {
    file: "BusJournalPage.test",
    kind: "key",
    text: "uz.railtech.erp.deal.won.v1",
    reason:
      "технический журнал шины для администратора: код типа события — его суть; вынос в «Хвосты» PR СЦ-7",
  },
  {
    file: "BusJournalPage.test",
    kind: "key",
    text: "uz.railtech.erp.invoice.issued.v1",
    reason:
      "технический журнал шины для администратора: код типа события — его суть; вынос в «Хвосты» PR СЦ-7",
  },
  {
    file: "TemplateCatalog.test",
    kind: "key",
    text: "counterparty.name",
    reason: "каталог шаблонов показывает коды полей подстановки администратору; «Хвосты» PR СЦ-7",
  },
  {
    file: "TemplateCatalog.test",
    kind: "key",
    text: "doc.requisites_and_signatures",
    reason: "каталог шаблонов показывает коды полей подстановки администратору; «Хвосты» PR СЦ-7",
  },
  {
    file: "TemplateCatalog.test",
    kind: "key",
    text: "doc.spec_table",
    reason: "каталог шаблонов показывает коды полей подстановки администратору; «Хвосты» PR СЦ-7",
  },
  {
    file: "TemplateCatalog.test",
    kind: "key",
    text: "doc.totals",
    reason: "каталог шаблонов показывает коды полей подстановки администратору; «Хвосты» PR СЦ-7",
  },
  {
    file: "CompanyPage.test",
    kind: "key",
    text: "counterparty.name",
    reason: "каталог шаблонов показывает коды полей подстановки администратору; «Хвосты» PR СЦ-7",
  },
  {
    file: "CompanyPage.test",
    kind: "key",
    text: "doc.requisites_and_signatures",
    reason: "каталог шаблонов показывает коды полей подстановки администратору; «Хвосты» PR СЦ-7",
  },
  {
    file: "CompanyPage.test",
    kind: "key",
    text: "doc.spec_table",
    reason: "каталог шаблонов показывает коды полей подстановки администратору; «Хвосты» PR СЦ-7",
  },
  {
    file: "CompanyPage.test",
    kind: "key",
    text: "doc.totals",
    reason: "каталог шаблонов показывает коды полей подстановки администратору; «Хвосты» PR СЦ-7",
  },
  {
    file: "CompanyPage.test",
    kind: "key",
    text: "doc.items_table",
    reason: "каталог шаблонов показывает коды полей подстановки администратору; «Хвосты» PR СЦ-7",
  },
  {
    file: "CompanyPage.test",
    kind: "key",
    text: "doc.signatures",
    reason: "каталог шаблонов показывает коды полей подстановки администратору; «Хвосты» PR СЦ-7",
  },
];

/** Ключи без перевода (`ns:key`), известные и отложенные: то же правило, что и выше. */
export interface AllowedMissingKey {
  file: string;
  key: string;
  reason: string;
}

export const ALLOWED_MISSING_KEYS: readonly AllowedMissingKey[] = [];
