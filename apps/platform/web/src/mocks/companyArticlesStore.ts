import type { CompanyArticleLanguage, CompanyArticleStatus } from "../shared/api/generated/model";

/**
 * Хранилище MSW для статей компании (W18A-P5, B-079). Живёт в `localStorage` страницы (как сессия мока): статью,
 * написанную администратором, видит менеджер после смены учётной записи в том же браузере. Без хранилища — в памяти.
 * Только для моков и тестов; демо-статьи вымышленные.
 */
const KEY = "rt-pf-mock-company-articles";

export interface StoredArticle {
  id: number;
  title: string;
  body: string;
  language: CompanyArticleLanguage;
  status: CompanyArticleStatus;
  createdBy: string;
  updatedBy: string;
  createdAt: string;
  updatedAt: string;
  publishedAt?: string;
}

interface State {
  articles: StoredArticle[];
  next: number;
}

const SEED_TIME = "2026-10-26T09:00:00.000Z";

/** Демо-статьи: две опубликованные и один черновик — экран и «Как у нас принято» не пустые. */
function seed(): State {
  return {
    next: 4,
    articles: [
      {
        id: 1,
        title: "Кто согласует договор",
        body: [
          "Договор с покупателем проходит три шага.",
          "",
          "## Порядок согласования",
          "",
          "1. Менеджер готовит договор из КП и прикрепляет расчёт.",
          "2. Юрист проверяет реквизиты и условия оплаты, срок — один рабочий день.",
          "3. Директор подписывает; без его резолюции договор клиенту не уходит.",
          "",
          "## Если срок горит",
          "",
          "- напишите юристу в чат и укажите **срок** в заголовке;",
          "- в отпуске юриста его замещает бухгалтер.",
        ].join("\n"),
        language: "ru",
        status: "published",
        createdBy: "Администратор Тестов",
        updatedBy: "Администратор Тестов",
        createdAt: SEED_TIME,
        updatedAt: "2026-10-27T10:30:00.000Z",
        publishedAt: "2026-10-27T10:30:00.000Z",
      },
      {
        id: 2,
        title: "Где лежат шаблоны писем",
        body: [
          "Шаблоны писем лежат в общей папке `Шаблоны/Письма` на общем диске.",
          "",
          "- Благодарность клиенту — `thanks.docx`.",
          "- Запрос реквизитов — `requisites.docx`.",
          "",
          "Новый шаблон добавляйте только через администратора.",
        ].join("\n"),
        language: "ru",
        status: "published",
        createdBy: "Администратор Тестов",
        updatedBy: "Администратор Тестов",
        createdAt: SEED_TIME,
        updatedAt: SEED_TIME,
        publishedAt: SEED_TIME,
      },
      {
        id: 3,
        title: "График отпусков на следующий год",
        body: "Черновик: заявки на отпуск собираем до 15 ноября, график утверждает директор.",
        language: "ru",
        status: "draft",
        createdBy: "Администратор Тестов",
        updatedBy: "Администратор Тестов",
        createdAt: SEED_TIME,
        updatedAt: "2026-10-28T08:00:00.000Z",
      },
    ],
  };
}

let memory: State | null = null;

export function readCompanyArticles(): State {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (raw) return JSON.parse(raw) as State;
  } catch {
    // Хранилище недоступно — состояние в памяти.
  }
  return memory ?? seed();
}

export function writeCompanyArticles(state: State): void {
  memory = state;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    // Остаётся копия в памяти.
  }
}

/** Вернуть демо-статьи (тесты вызывают в `beforeEach`). */
export function resetCompanyArticlesMock(): void {
  memory = null;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // Нечего сбрасывать.
  }
}

/** Убрать все статьи (пустое состояние экрана). */
export function clearCompanyArticlesMock(): void {
  writeCompanyArticles({ articles: [], next: 1 });
}
