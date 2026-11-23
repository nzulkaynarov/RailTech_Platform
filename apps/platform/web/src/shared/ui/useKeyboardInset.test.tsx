import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { keyboardInsetOf, useKeyboardInset } from "./useKeyboardInset";

class FakeViewport extends EventTarget {
  height = 800;
  offsetTop = 0;
}

function Consumer() {
  useKeyboardInset();
  return null;
}

describe("keyboardInsetOf", () => {
  it("is 0 without visualViewport and for a toolbar-sized change", () => {
    expect(keyboardInsetOf(800, null)).toBe(0);
    expect(keyboardInsetOf(800, { height: 740, offsetTop: 0 })).toBe(0);
  });
  it("is the covered height once the keyboard is open", () => {
    expect(keyboardInsetOf(844, { height: 520, offsetTop: 0 })).toBe(324);
    // iOS scrolls the visual viewport down when focusing: offsetTop is not part of the keyboard
    expect(keyboardInsetOf(844, { height: 520, offsetTop: 100 })).toBe(224);
  });
  it("is 0 while pinch-zoomed: a smaller visual viewport is not the keyboard", () => {
    expect(keyboardInsetOf(844, { height: 422, offsetTop: 0, scale: 2 })).toBe(0);
    expect(keyboardInsetOf(844, { height: 520, offsetTop: 0, scale: 1 })).toBe(324);
  });
});

describe("useKeyboardInset", () => {
  const original = Object.getOwnPropertyDescriptor(window, "visualViewport");
  let vv: FakeViewport;
  beforeEach(() => {
    vv = new FakeViewport();
    Object.defineProperty(window, "visualViewport", { value: vv, configurable: true });
    Object.defineProperty(window, "innerHeight", { value: 800, configurable: true });
  });
  afterEach(() => {
    if (original) Object.defineProperty(window, "visualViewport", original);
    else Reflect.deleteProperty(window, "visualViewport");
  });

  it("publishes the offset on <html> while mounted and clears it after", () => {
    const { unmount } = render(<Consumer />);
    const root = document.documentElement;
    expect(root.style.getPropertyValue("--pf-kb-inset")).toBe("0px");
    expect(root.dataset["kb"]).toBeUndefined();

    act(() => {
      vv.height = 480;
      vv.dispatchEvent(new Event("resize"));
    });
    expect(root.style.getPropertyValue("--pf-kb-inset")).toBe("320px");
    expect(root.dataset["kb"]).toBe("open");

    act(() => {
      vv.height = 800;
      vv.dispatchEvent(new Event("resize"));
    });
    expect(root.dataset["kb"]).toBeUndefined();

    unmount();
    expect(root.style.getPropertyValue("--pf-kb-inset")).toBe("");
  });

  it("is shared: the offset lives until the last consumer unmounts", () => {
    const a = render(<Consumer />);
    const b = render(<Consumer />);
    a.unmount();
    expect(document.documentElement.style.getPropertyValue("--pf-kb-inset")).toBe("0px");
    b.unmount();
    expect(document.documentElement.style.getPropertyValue("--pf-kb-inset")).toBe("");
  });
});
