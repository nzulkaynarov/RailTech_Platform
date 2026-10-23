import { InvalidationTopic } from "./generated/model";

export const EVENT_STREAM_URL = "/api/v1/events/stream";
/** Переподключение после обрыва: 1, 2, 4, 8, 16 секунд, дальше раз в 30. */
export const BACKOFF_MS = [1_000, 2_000, 4_000, 8_000, 16_000, 30_000] as const;

const TOPICS = new Set<string>(Object.values(InvalidationTopic));

/** Часть `EventSource`, которой пользуется клиент (подменяется в тестах). */
export interface StreamSource {
  onopen: ((event: Event) => void) | null;
  onerror: ((event: Event) => void) | null;
  addEventListener(type: string, listener: (event: MessageEvent<string>) => void): void;
  close(): void;
}

export interface EventStreamOptions {
  url?: string;
  createSource?: (url: string) => StreamSource;
  /** Подсказка BFF: эти темы нужно перезапросить обычными API. */
  onHint: (topics: InvalidationTopic[], reason: string) => void;
  /** Поток открылся заново после обрыва: подсказки могли пропасть, нужен полный перезапрос. */
  onResync: () => void;
  onLive: (live: boolean) => void;
  /** 0…1; по умолчанию `Math.random` (разброс задержки переподключения ±20 %, чтобы вкладки не стучались разом). */
  random?: () => number;
}

/** Разбор данных кадра `invalidate`; мусор и неизвестные темы отбрасываются. */
export function parseHint(raw: string): { topics: InvalidationTopic[]; reason: string } | null {
  try {
    const body: unknown = JSON.parse(raw);
    if (typeof body !== "object" || body === null) return null;
    const { topics, reason } = body as { topics?: unknown; reason?: unknown };
    if (!Array.isArray(topics)) return null;
    const known = topics.filter(
      (topic): topic is InvalidationTopic => typeof topic === "string" && TOPICS.has(topic),
    );
    return known.length > 0
      ? { topics: known, reason: typeof reason === "string" ? reason : "" }
      : null;
  } catch {
    return null;
  }
}

/**
 * Клиент потока подсказок BFF (`GET /api/v1/events/stream`, SSE). Переподключение ведёт сам (с задержкой по
 * `BACKOFF_MS`), а не браузер: `EventSource` закрывается на любой ошибке, иначе он стучится раз в три секунды и без
 * разброса. Пока поток не открыт, `onLive(false)` — приложение опрашивает как раньше.
 */
export class EventStreamClient {
  private source: StreamSource | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private attempt = 0;
  private wasLive = false;
  private stopped = true;

  constructor(private readonly options: EventStreamOptions) {}

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
    this.drop();
    this.options.onLive(false);
  }

  private connect(): void {
    this.timer = null;
    const url = this.options.url ?? EVENT_STREAM_URL;
    const source = this.options.createSource
      ? this.options.createSource(url)
      : (new EventSource(url, { withCredentials: true }) as StreamSource);
    this.source = source;
    source.onopen = () => {
      if (this.source !== source) return;
      this.attempt = 0;
      if (this.wasLive) this.options.onResync();
      this.wasLive = true;
      this.options.onLive(true);
    };
    source.addEventListener("invalidate", (event) => {
      if (this.source !== source) return;
      const hint = parseHint(event.data);
      if (hint) this.options.onHint(hint.topics, hint.reason);
    });
    source.onerror = () => {
      if (this.source !== source) return;
      this.drop();
      this.options.onLive(false);
      this.schedule();
    };
  }

  private drop(): void {
    const source = this.source;
    this.source = null;
    if (source) {
      source.onopen = null;
      source.onerror = null;
      source.close();
    }
  }

  private schedule(): void {
    if (this.stopped) return;
    const base = BACKOFF_MS[Math.min(this.attempt, BACKOFF_MS.length - 1)] ?? BACKOFF_MS[0];
    this.attempt += 1;
    const jitter = 0.8 + 0.4 * (this.options.random ?? Math.random)();
    this.timer = setTimeout(
      () => {
        this.connect();
      },
      Math.round(base * jitter),
    );
  }
}
