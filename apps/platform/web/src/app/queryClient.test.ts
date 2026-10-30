import { QueryObserver } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { createQueryClient, keepSamePathData } from "./queryClient";

function deferred<T>() {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe("queryClient: данные на месте при смене условий (UX-1c, S8)", () => {
  it("тот же адрес с другими параметрами — прежние данные; другой адрес — нет", () => {
    const keep = keepSamePathData(["/api/v1/crm/leads", { scope: "mine" }]);
    const sameList = { queryKey: ["/api/v1/crm/leads", { scope: "all" }] } as never;
    const otherCard = { queryKey: ["/api/v1/crm/leads/L-1"] } as never;
    expect(keep(["прежние"], sameList)).toEqual(["прежние"]);
    expect(keep({ id: "L-1" }, otherCard)).toBeUndefined();
    expect(keep(undefined, undefined)).toBeUndefined();
  });

  it("наблюдатель списка при смене параметров показывает прежние строки до ответа, затем новые", async () => {
    const client = createQueryClient({ retry: false });
    const second = deferred<string[]>();
    const observer = new QueryObserver<string[]>(client, {
      queryKey: ["/api/v1/crm/leads", { scope: "all" }],
      queryFn: () => Promise.resolve(["все"]),
    });
    const unsubscribe = observer.subscribe(() => undefined);
    await client.getQueryCache().find({ queryKey: ["/api/v1/crm/leads", { scope: "all" }] })
      ?.promise;
    await Promise.resolve();
    expect(observer.getCurrentResult().data).toEqual(["все"]);

    observer.setOptions({
      queryKey: ["/api/v1/crm/leads", { scope: "mine" }],
      queryFn: () => second.promise,
    });
    const during = observer.getCurrentResult();
    expect(during.isPending).toBe(false);
    expect(during.isPlaceholderData).toBe(true);
    expect(during.data).toEqual(["все"]);

    second.resolve(["мои"]);
    await second.promise;
    await Promise.resolve();
    expect(observer.getCurrentResult().isPlaceholderData).toBe(false);
    expect(observer.getCurrentResult().data).toEqual(["мои"]);

    // Карточка другого объекта — свой адрес: скелетон, а не чужая карточка
    observer.setOptions({
      queryKey: ["/api/v1/crm/leads/L-2"],
      queryFn: () => new Promise<string[]>(() => undefined),
    });
    expect(observer.getCurrentResult().isPending).toBe(true);
    expect(observer.getCurrentResult().data).toBeUndefined();
    unsubscribe();
  });

  it("свой placeholderData экрана не подменяется", () => {
    const client = createQueryClient();
    const own = () => ["своё"];
    const options = client.defaultQueryOptions<string[]>({
      queryKey: ["/x"],
      placeholderData: own,
    });
    expect(options.placeholderData).toBe(own);
  });
});
