import { describe, expect, it } from "vitest";

import i18n, { resources } from "./index";

function keys(obj: object, prefix = ""): string[] {
  return Object.entries(obj).flatMap(([k, v]) =>
    typeof v === "object" && v !== null ? keys(v as object, `${prefix}${k}.`) : [`${prefix}${k}`],
  );
}

describe("i18n", () => {
  it("defaults to Russian", () => {
    expect(i18n.language).toBe("ru");
    expect(i18n.t("scaffold.title")).toBe("Платформа — каркас P0");
  });

  it.each(["uz", "en"] as const)("%s has the same keys as ru", (lng) => {
    expect(keys(resources[lng].common).sort()).toEqual(keys(resources.ru.common).sort());
  });
});
