import { describe, expect, it } from "vitest";

import { orderBy } from "./orderBy";

const rows = [
  { n: "B", v: 2 },
  { n: "A", v: null },
  { n: "C", v: 1 },
  { n: "D", v: 2 },
];
const fields = {
  n: (row: (typeof rows)[number]) => row.n,
  v: (row: (typeof rows)[number]) => row.v,
};
const names = (list: typeof rows) => list.map((row) => row.n).join("");

describe("orderBy (моки порядка Х-15б)", () => {
  it("пустые значения в конце в обе стороны, равные — в прежнем порядке", () => {
    expect(names(orderBy(rows, "v", fields))).toBe("CBDA");
    expect(names(orderBy(rows, "-v", fields))).toBe("BDCA");
  });

  it("поле вне списка не сортирует", () => {
    expect(names(orderBy(rows, "secret", fields))).toBe("BACD");
    expect(names(orderBy(rows, null, fields))).toBe("BACD");
  });
});
