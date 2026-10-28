import type { Notification, TicketStatus, TicketSubject } from "../shared/api/generated/model";

/**
 * Хранилище MSW для обращений сотрудников и ленты CRM в колокольчике (W15-H7). Живёт в `localStorage` страницы (как сессия
 * мока): обращение, написанное менеджером, видит администратор после смены учётной записи в том же браузере. Без
 * хранилища — в памяти. Только для моков и тестов; данные вымышленные.
 */
const KEY = "rt-pf-mock-tickets";
const RATE_PER_HOUR = 5;

export interface StoredMessage {
  author_name: string;
  body: string;
  created_at: string;
}

export interface StoredTicket {
  seq: number;
  subject: TicketSubject;
  status: TicketStatus;
  authorId: string;
  authorName: string;
  authorRole?: string;
  page?: string;
  body: string;
  messages: StoredMessage[];
  createdAt: string;
  updatedAt: string;
  resolvedAt?: string;
}

export interface StoredNote {
  seq: number;
  userId: string;
  kind: string;
  tab: Notification["tab"];
  title: string;
  subtitle?: string;
  ticketNumber?: string;
  createdAt: string;
  read: boolean;
}

interface State {
  tickets: StoredTicket[];
  notes: StoredNote[];
  nextTicket: number;
  nextNote: number;
}

const EMPTY: State = { tickets: [], notes: [], nextTicket: 1, nextNote: 1 };
let memory: State | null = null;

export function readTickets(): State {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (raw) return { ...EMPTY, ...(JSON.parse(raw) as Partial<State>) };
  } catch {
    // Хранилище недоступно — состояние в памяти.
  }
  return memory ?? { ...EMPTY, tickets: [], notes: [] };
}

export function writeTickets(state: State): void {
  memory = state;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    // Остаётся копия в памяти.
  }
}

export function resetTicketsMock(): void {
  memory = null;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // Нечего сбрасывать.
  }
}

export const numberOf = (seq: number) => `ОБР-${String(seq).padStart(4, "0")}`;
export const seqOf = (number: string) => {
  const hit = /^ОБР-(\d{1,9})$/.exec(number);
  return hit ? Number(hit[1]) : undefined;
};

/** Не больше пяти обращений в час от одного сотрудника (как CRM). */
export function rateExceeded(state: State, userId: string, now = Date.now()): boolean {
  const recent = state.tickets.filter(
    (t) => t.authorId === userId && now - new Date(t.createdAt).getTime() < 3_600_000,
  );
  return recent.length >= RATE_PER_HOUR;
}

export function addNote(state: State, note: Omit<StoredNote, "seq" | "read" | "createdAt">): void {
  state.notes.push({
    ...note,
    seq: state.nextNote++,
    read: false,
    createdAt: new Date().toISOString(),
  });
}
