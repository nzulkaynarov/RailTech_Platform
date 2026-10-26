import type {
  KbChunk,
  KbDocument,
  KbGap,
  KbProduct,
  ReplyTemplate,
} from "../../shared/api/generated/model";
import schemas from "./botSettingsSchemas.json";
import values from "./botSettingsValues.json";

/**
 * Состояние моков «База знаний» и «Настройки бота» (W13-A5): документы, пробелы, продукты, шаблоны ответов, значения
 * настроек. Данные выдуманы. Хранится в `localStorage` страницы (обработчики MSW работают в потоке страницы), поэтому
 * переживает перезагрузку, как CRM; без хранилища — в памяти. Схемы разделов настроек — настоящие, из Pydantic CRM
 * (`model_json_schema`, без значений по умолчанию), значения — модели по умолчанию с выдуманной компанией.
 */
export const MOCK_NOW = "2026-10-26T09:12:00Z";
const EARLIER = "2026-10-20T08:30:00Z";
const KEY = "rt-pf-mock-bot-kb";

export interface KbMock {
  documents: KbDocument[];
  chunks: Record<string, KbChunk[]>;
  gaps: KbGap[];
  products: KbProduct[];
  templates: ReplyTemplate[];
  settings: Record<string, Record<string, unknown>>;
  nextId: number;
  /** Реплики песочницы: сколько ходов сделано (для проверки «начать заново») */
  sandboxTurns: number;
}

function chunks(document: number, base: string): KbChunk[] {
  return [
    {
      id: document * 100 + 1,
      position: 0,
      heading_path: base,
      content: `${base}. Условия действуют для заказов по договору поставки; детали уточняет менеджер.`,
      token_count: 24,
    },
    {
      id: document * 100 + 2,
      position: 1,
      heading_path: `${base} > Исключения`,
      content:
        "Для нестандартных заказов сроки и стоимость согласуются отдельно (вымышленный пример).",
      token_count: 19,
    },
    {
      id: document * 100 + 3,
      position: 2,
      heading_path: `${base} > Контакты`,
      content: "Вопросы по заказу — менеджеру компании в рабочее время.",
      token_count: 11,
    },
  ];
}

function doc(id: number, over: Partial<KbDocument> & Pick<KbDocument, "title">): KbDocument {
  return {
    id,
    product_key: null,
    language: "ru",
    source_type: "file",
    mime: "text/markdown",
    version: 1,
    is_active: true,
    ingest_status: "done",
    ingest_error: null,
    chunk_count: 3,
    created_at: EARLIER,
    updated_at: MOCK_NOW,
    ...over,
  };
}

function gap(id: number, over: Partial<KbGap> & Pick<KbGap, "question">): KbGap {
  return {
    id,
    lead_id: null,
    language: "ru",
    best_score: 0.41,
    occurrences: 1,
    status: "open",
    resolved_document_id: null,
    created_at: EARLIER,
    updated_at: MOCK_NOW,
    ...over,
  };
}

export function initialKb(): KbMock {
  const documents = [
    doc(1, { title: "Сроки и условия поставки", product_key: "rails" }),
    doc(2, { title: "Гарантия на продукцию", source_type: "manual", updated_at: EARLIER }),
    doc(3, { title: "Yetkazib berish shartlari", language: "uz", product_key: "rails" }),
    doc(4, {
      title: "Warranty and returns",
      language: "en",
      ingest_status: "processing",
      chunk_count: 0,
    }),
    doc(5, {
      title: "Прайс-лист (черновик)",
      ingest_status: "failed",
      ingest_error: "Не удалось разобрать таблицу на странице 3",
      chunk_count: 0,
    }),
    doc(6, { title: "Устаревший регламент отгрузки", is_active: false, updated_at: EARLIER }),
  ];
  return {
    documents,
    chunks: Object.fromEntries(
      documents.filter((d) => d.chunk_count > 0).map((d) => [String(d.id), chunks(d.id, d.title)]),
    ),
    gaps: [
      gap(1, {
        question: "Есть ли гарантия на крепёж?",
        occurrences: 4,
        lead_id: 2041,
        best_score: 0.52,
      }),
      gap(2, { question: "Можно ли оплатить частями?", occurrences: 2, lead_id: 2038 }),
      gap(3, {
        question: "Do you deliver to Samarkand?",
        language: "en",
        occurrences: 1,
        lead_id: 2044,
      }),
      gap(4, {
        question: "Qanday to‘lov usullari bor?",
        language: "uz",
        occurrences: 3,
        best_score: null,
      }),
      gap(5, {
        question: "Какой минимальный заказ по рельсам?",
        status: "resolved",
        resolved_document_id: 1,
        occurrences: 5,
      }),
      gap(6, { question: "Расскажите анекдот", status: "ignored", best_score: 0.12 }),
    ],
    products: [
      { key: "rails", name: "Рельсы", description: null, is_active: true },
      {
        key: "fasteners",
        name: "Крепёж",
        description: "Болты, клеммы, подкладки",
        is_active: true,
      },
      { key: "switches", name: "Стрелочные переводы", description: null, is_active: true },
    ],
    templates: [
      {
        id: 1,
        title: "Пришлю КП сегодня",
        text: {
          ru: "{name}, добрый день! Пришлю коммерческое предложение сегодня до конца дня. {manager}",
          uz: "{name}, hayrli kun! Tijoriy taklifni bugun kun oxirigacha yuboraman. {manager}",
          en: "Hello {name}! I will send the quote by the end of today. {manager}",
        },
        updated_at: EARLIER,
      },
      {
        id: 2,
        title: "Спасибо за обращение",
        text: {
          ru: "{name}, спасибо за обращение! Мы свяжемся с вами в рабочее время.",
          uz: "",
          en: "",
        },
        updated_at: MOCK_NOW,
      },
    ],
    settings: structuredClone(values),
    nextId: 100,
    sandboxTurns: 0,
  };
}

/** Схемы разделов настроек — как отдаёт CRM (без значений по умолчанию). */
export const SETTINGS_SCHEMAS = schemas as Record<string, Record<string, unknown>>;

let memory: KbMock | null = null;

function withDemoCompany(state: KbMock): KbMock {
  const company = state.settings["company"] ?? {};
  state.settings["company"] = {
    ...company,
    name: "RailTech (демо)",
    phone: "+998 71 000 00 00",
    site: "https://demo.railtech.example",
    address: "г. Ташкент, ул. Демонстрационная, 1",
    crm_base_url: "https://crm.demo.railtech.example",
  };
  return state;
}

export function readKb(): KbMock {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (raw) return JSON.parse(raw) as KbMock;
  } catch {
    if (memory) return structuredClone(memory);
  }
  return withDemoCompany(initialKb());
}

export function writeKb(state: KbMock): void {
  memory = state;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    // Остаётся копия в памяти.
  }
}

export function resetKb(): void {
  memory = null;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // Нечего сбрасывать.
  }
}
