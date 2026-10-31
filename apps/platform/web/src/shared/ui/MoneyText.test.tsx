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

  it("код UZS из ответа — «сум» / «so‘m», другая валюта — код, ноль и минус", () => {
    const { container } = renderUi(
      <>
        <MoneyText value="30000000.00" currency="UZS" />
        <MoneyText value={-1500} currency="USD" />
        <MoneyText value={0} currency="UZS" />
      </>,
    );
    const spans = container.querySelectorAll("span.pf-num");
    expect(spans[0]?.textContent).toBe(`30${NBSP}000${NBSP}000${NBSP}сум`);
    expect(spans[1]?.textContent).toBe(`−1${NBSP}500${NBSP}USD`);
    expect(spans[2]?.textContent).toBe(`0${NBSP}сум`);
  });

  it("узбекский интерфейс — «so‘m» и для кода UZS", () => {
    const { container } = renderUi(<MoneyText value={1000} currency="UZS" />, { language: "uz" });
    expect(container.textContent).toBe(`1${NBSP}000${NBSP}so‘m`);
  });
});
