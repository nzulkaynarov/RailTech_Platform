import type {
  LetterCard,
  LetterFile,
  LetterZone,
  ResolutionCandidate,
} from "../../shared/api/generated/model";

/**
 * Вымышленные входящие письма EDS для MSW (D1-3, BFF 0.16.0): те же формы, что вернёт BFF по `platform-bff.yaml`. Названия
 * компаний и имена выдуманы (репозиторий публичный). Состояние живёт в памяти страницы: решение директора меняет письмо, и
 * следующий запрос списка и карточки его видит; `resetLetters()` возвращает исходное (тесты).
 */
export const ERP_DOWN_DEAL_NUMBER = "ЗВ-2026-107";

const FILE: LetterFile = {
  id: "30000000-0000-4000-8000-000000000001",
  name: "запрос-на-кп.pdf",
  content_type: "application/pdf",
  size: 184_320,
  uploaded_at: "2026-10-24T09:14:00Z",
};
const SPEC_FILE: LetterFile = {
  id: "30000000-0000-4000-8000-000000000002",
  name: "техзадание.docx",
  content_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  size: 52_480,
  uploaded_at: "2026-10-24T09:14:30Z",
};

const person = (id: string, name: string) => ({
  id,
  name,
  initials: name
    .split(" ")
    .slice(0, 2)
    .map((p) => p[0])
    .join("")
    .toUpperCase(),
});
export const DIRECTOR = person("1", "Демо Директоров");
const MANAGER = person("2", "Демо Менеджеров");

interface Seed {
  n: number;
  subject: string;
  summary: string;
  client: string;
  inn: string;
  clientId: string;
  urgent?: boolean;
  files?: LetterFile[];
  title: string;
}

const SEEDS: readonly Seed[] = [
  {
    n: 104,
    subject: "Запрос коммерческого предложения на стрелочные приводы",
    summary:
      "Просим рассмотреть поставку 12 стрелочных приводов СП-6 с монтажом до конца квартала.\nНужны сроки поставки, гарантийные условия и стоимость шефмонтажа.",
    client: "ООО «Демо-Рейл»",
    inn: "300123456",
    clientId: "42",
    urgent: true,
    files: [FILE, SPEC_FILE],
    title: "Стрелочные приводы",
  },
  {
    n: 105,
    subject: "Цены на рельсовые скрепления",
    summary: "Нужен расчёт на 4 000 комплектов скреплений для участка пути.",
    client: "АО «Демо-Транс»",
    inn: "300654321",
    clientId: "43",
    files: [FILE],
    title: "Рельсовые скрепления",
  },
  {
    n: 106,
    subject: "Монтаж и наладка устройств автоблокировки",
    summary: "Просим предложить монтаж и наладку устройств автоблокировки на двух перегонах.",
    client: "ООО «Демо-Сигнал»",
    inn: "300777888",
    clientId: "44",
    title: "Автоблокировка",
  },
  {
    n: 107,
    subject: "Поставка кабельной продукции",
    summary: "Нужен кабель сигнально-блокировочный, 6 км, с доставкой.",
    client: "ООО «Демо-Кабель»",
    inn: "300999111",
    clientId: "45",
    title: "Кабель СБ",
  },
];

function awaiting(seed: Seed): LetterCard {
  const number = `ВХ-${String(seed.n)}/26`;
  const dealNumber = `ЗВ-2026-${String(seed.n)}`;
  return {
    id: `20000000-0000-4000-8000-${String(seed.n).padStart(12, "0")}`,
    number,
    status: "awaiting_resolution",
    subject: seed.subject,
    summary: seed.summary,
    urgent: seed.urgent ?? false,
    received_at: "2026-10-24",
    registered_at: "2026-10-24T09:15:00Z",
    registered_by: null,
    addressee: DIRECTOR,
    manager: MANAGER,
    sender: { name: seed.client, inn: seed.inn, contact: "Алия Демо" },
    sender_ref: { number: `исх-${String(seed.n - 80)}`, date: "2026-10-22" },
    client: {
      id: seed.clientId,
      name: seed.client,
      inn: seed.inn,
      path: `/crm/clients/${seed.clientId}`,
    },
    request: {
      number: dealNumber,
      title: dealNumber === ERP_DOWN_DEAL_NUMBER ? null : seed.title,
      path: `/crm/requests?request=${encodeURIComponent(dealNumber)}&panel=open&tab=card`,
    },
    stage: "RESOLUTION",
    lost_at_step: null,
    files: seed.files ?? [],
    resolution: null,
    return_comment: null,
    reject_reason: null,
    journal: [
      {
        at: "2026-10-24T09:15:00Z",
        action: "letter.registered",
        by: null,
        comment: null,
      },
    ],
    sources: { crm: "ok", erp: dealNumber === ERP_DOWN_DEAL_NUMBER ? "unavailable" : "ok" },
  };
}

function decided(n: number, patch: Partial<LetterCard>): LetterCard {
  const base = awaiting({
    n,
    subject: "Поставка щебня для ремонта пути",
    summary: "Нужна поставка щебня фракции 25–60, 2 000 тонн.",
    client: "ООО «Демо-Путь»",
    inn: "300555222",
    clientId: "46",
    title: "Щебень",
  });
  return { ...base, ...patch };
}

function seedLetters(): LetterCard[] {
  return [
    ...SEEDS.map(awaiting),
    decided(101, {
      status: "resolved",
      stage: "CALCULATION",
      resolution: {
        text: "Посчитать с запасом по складу, срок поставки — до конца ноября.",
        assignees: [
          { person: person("31", "Демо Снабженцев"), zone: "goods" },
          { person: person("41", "Демо Инженеров"), zone: "services" },
        ],
        due: "2026-10-30",
        min_margin_pct: "15",
        decided_by: DIRECTOR,
        decided_at: "2026-10-26T08:00:00Z",
      },
      journal: [
        { at: "2026-10-24T09:15:00Z", action: "letter.registered", by: null, comment: null },
        {
          at: "2026-10-26T08:00:00Z",
          action: "letter.resolved",
          by: DIRECTOR,
          comment: "Посчитать с запасом по складу, срок поставки — до конца ноября.",
        },
      ],
    }),
    decided(102, {
      status: "returned",
      stage: "REQUEST",
      subject: "Письмо без реквизитов",
      return_comment: "Нет объёма и сроков. Уточните у клиента и подайте заново.",
    }),
    decided(103, {
      status: "rejected",
      stage: "LOST",
      lost_at_step: 2,
      subject: "Предложение сотрудничества от агентства",
      reject_reason: "Не наш профиль.",
    }),
  ];
}

let letters = seedLetters();

export const readLetters = (): LetterCard[] => letters;
export const writeLetters = (next: LetterCard[]): void => {
  letters = next;
};
export function resetLetters(): void {
  letters = seedLetters();
}

export function findLetter(ref: string): LetterCard | undefined {
  return letters.find((l) => l.id === ref || l.number === ref);
}

/** Кандидаты в исполнители по зонам: в «товарах» двое (нужно выбрать), в остальных по одному (выбирается сам). */
export const CANDIDATES: Record<LetterZone, ResolutionCandidate[]> = {
  goods: [
    { id: "31", name: "Демо Снабженцев", initials: "ДС", position: "Специалист по снабжению" },
    { id: "32", name: "Образец Закупщиков", initials: "ОЗ", position: "Закупщик" },
  ],
  services: [{ id: "41", name: "Демо Инженеров", initials: "ДИ", position: "Главный инженер" }],
  payment_terms: [{ id: "51", name: "Демо Бухгалтеров", initials: "ДБ", position: "Бухгалтер" }],
};
