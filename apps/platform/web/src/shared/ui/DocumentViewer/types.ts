/** Состояние и действия просмотра — одинаковые для PDF и картинок, их читает панель инструментов. */
export interface ViewerSearch {
  /** Идёт ли поиск (запрос не пуст) и сколько совпадений: `total === 0` — «не найдено» */
  query: string;
  current: number;
  total: number;
  find: (query: string) => void;
  next: () => void;
  prev: () => void;
  clear: () => void;
}

export interface ViewerApi {
  status: "loading" | "ready" | "error";
  pages: number;
  page: number;
  /** Масштаб в процентах для подписи */
  percent: number;
  /** Включён режим «По ширине» (масштаб следует за шириной панели) */
  fitted: boolean;
  fit: () => void;
  actual: () => void;
  zoomIn: () => void;
  zoomOut: () => void;
  goTo: (page: number) => void;
  /** У картинок поиска по тексту нет */
  search: ViewerSearch | null;
}
