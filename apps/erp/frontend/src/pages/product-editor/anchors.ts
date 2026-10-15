/**
 * Якоря секций страницы-редактора карточки (R3): индикатор полноты слева называет
 * недостающее и ВЕДЁТ к месту ввода — каждый код требования сервера
 * (`catalog/completeness.py`) знает свою секцию. Паттерн Akeneo: completeness
 * не упрёк, а маршрут.
 */
export const SECTION_IDS = {
  basics: 'pe-basics',
  classification: 'pe-classification',
  specifications: 'pe-specifications',
  media: 'pe-media',
  commerce: 'pe-commerce',
  publication: 'pe-publication',
  actions: 'pe-actions',
} as const;

/** Код требования полноты → секция, где это поле заполняется. */
export const SECTION_BY_REQUIREMENT: Record<string, string> = {
  name: SECTION_IDS.basics,
  identity: SECTION_IDS.basics,
  uom: SECTION_IDS.basics,
  category: SECTION_IDS.classification,
  hs_code: SECTION_IDS.classification,
  list_price: SECTION_IDS.publication,
};

export function scrollToSection(sectionId: string) {
  document.getElementById(sectionId)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}
