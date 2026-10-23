import type { StreamSource } from "../shared/api/eventStream";

/** `EventSource` для тестов: тест сам открывает поток, шлёт кадры и обрывает соединение. */
export class FakeEventSource implements StreamSource {
  static instances: FakeEventSource[] = [];
  static get last(): FakeEventSource {
    const source = FakeEventSource.instances.at(-1);
    if (!source) throw new Error("EventSource не создавался");
    return source;
  }
  static reset(): void {
    FakeEventSource.instances = [];
  }

  onopen: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  closed = false;
  private readonly listeners = new Map<string, ((event: MessageEvent<string>) => void)[]>();

  constructor(
    readonly url: string,
    readonly init?: EventSourceInit,
  ) {
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: MessageEvent<string>) => void): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  close(): void {
    this.closed = true;
  }

  open(): void {
    this.onopen?.(new Event("open"));
  }

  fail(): void {
    this.onerror?.(new Event("error"));
  }

  emit(type: string, data: unknown): void {
    const event = new MessageEvent<string>(type, {
      data: typeof data === "string" ? data : JSON.stringify(data),
    });
    this.listeners.get(type)?.forEach((listener) => {
      listener(event);
    });
  }
}
