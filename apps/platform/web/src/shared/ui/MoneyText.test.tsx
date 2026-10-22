import { describe, expect, it } from "vitest";

import { NBSP } from "../lib/money";
import { renderUi } from "../../test/renderUi";
import { MoneyText } from "./MoneyText";

describe("MoneyText", () => {
  it("«1 234 567 сум» с неразрывными пробелами и tabular-nums", () => {
    const { container } = renderUi(<MoneyText value={1234567} />);
    const span = container.querySelector("span.pf-num");
    expect(span?.textContent).toBe(`1${NBSP}234${NBSP}567${NBSP}сум`);
  });

  it("жирный итог, без валюты, пустое значение", () => {
    const { container } = renderUi(
      <>
        <MoneyText value="134400000.00" strong />
        <MoneyText value={5} currency={false} />
        <MoneyText value={null} />
      </>,
    );
    const spans = container.querySelectorAll("span.pf-num");
    expect(spans[0]).toHaveStyle({ fontWeight: "600" });
    expect(spans[1]?.textContent).toBe("5");
    expect(spans[2]?.textContent).toBe("—");
  });

  it("валюта по языку интерфейса", () => {
    const { container } = renderUi(<MoneyText value={1000} />, { language: "en" });
    expect(container.textContent).toBe(`1,000${NBSP}UZS`);
  });
});
