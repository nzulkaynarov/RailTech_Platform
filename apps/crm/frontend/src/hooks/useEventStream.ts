import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { rawFetch } from "../api/http";
import { keys } from "../api/queries";

export type CrmEvent = {
  type: "message.created" | "lead.updated" | "escalation.updated";
  lead_id?: number | null;
  /** Только `message.created`: кто написал и чей лид — для звука у менеджера (Q-010). */
  role?: string;
  assigned_user_id?: number | null;
};

const RETRY_MS = 3000;

/** Разбор SSE-потока: события разделены пустой строкой, данные — в строках `data:`. */
export function parseSse(buffer: string): { events: CrmEvent[]; rest: string } {
  const chunks = buffer.split("\n\n");
  const rest = chunks.pop() ?? "";
  const events: CrmEvent[] = [];
  for (const chunk of chunks) {
    const data = chunk
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trim())
      .join("");
    if (!data) continue;
    try {
      events.push(JSON.parse(data) as CrmEvent);
    } catch {
      // повреждённое событие пропускаем — данные всё равно перечитываются
    }
  }
  return { events, rest };
}

/** Какие запросы перечитать по событию. */
export function keysFor(event: CrmEvent): readonly (readonly unknown[])[] {
  const lead = event.lead_id ?? undefined;
  const common = [keys.inbox, keys.serviceRequests, ["leads"]] as const;
  return lead === undefined ? common : [...common, ["lead", lead]];
}

/**
 * Читает поток до обрыва. `onOpen` — только после успешного ответа сервера: до этого
 * соединения нет, и индикатор в шапке не должен показывать «Онлайн».
 */
export async function consume(
  signal: AbortSignal,
  onEvent: (event: CrmEvent) => void,
  onOpen: () => void = () => undefined,
): Promise<void> {
  const response = await rawFetch("/api/v1/stream", {
    signal,
    headers: { Accept: "text/event-stream" },
  });
  if (!response.ok || !response.body) throw new Error(`stream ${String(response.status)}`);
  onOpen();
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    const parsed = parseSse(buffer + value);
    buffer = parsed.rest;
    parsed.events.forEach(onEvent);
  }
}

/** Подписка на `GET /api/v1/stream`; при обрыве — переподключение и перечитывание данных. */
export function useEventStream(
  enabled: boolean,
  onExtra: (event: CrmEvent) => void = () => undefined,
): boolean {
  const client = useQueryClient();
  const [live, setLive] = useState(false);
  // Обработчик меняется при каждом рендере — держим последний в ref, не переподключаясь.
  const extra = useRef(onExtra);
  useEffect(() => {
    extra.current = onExtra;
  }, [onExtra]);

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    const onEvent = (event: CrmEvent) => {
      for (const queryKey of keysFor(event)) void client.invalidateQueries({ queryKey });
      extra.current(event);
    };
    const loop = async () => {
      while (!controller.signal.aborted) {
        try {
          await consume(controller.signal, onEvent, () => {
            setLive(true);
            // пока связи не было, события могли пропасть — перечитываем всё
            void client.invalidateQueries();
          });
        } catch {
          // сеть/401 — повтор после паузы
        }
        setLive(false);
        await new Promise((resolve) => setTimeout(resolve, RETRY_MS));
      }
    };
    void loop();
    return () => {
      controller.abort();
    };
  }, [client, enabled]);

  return live;
}
