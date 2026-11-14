import { useCallback } from "react";
import { useSearchParams } from "react-router";

import { useViewport } from "../../app/shell/useViewport";

/**
 * Открыть и закрыть боковое окно для формы в `Sheet` (§4.1a): на широком экране окно открывается по адресу
 * (`?panel=open&tab=…`), на телефоне форма — лист на весь экран и адрес не меняется.
 */
export function useSheetPanel(tab = "card"): { open: () => void; close: () => void } {
  const { mobile } = useViewport();
  const [, setParams] = useSearchParams();
  const apply = useCallback(
    (show: boolean) => {
      if (mobile) return;
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (show) {
            next.set("panel", "open");
            next.set("tab", tab);
          } else {
            next.delete("panel");
            next.delete("tab");
          }
          return next;
        },
        { replace: true },
      );
    },
    [mobile, setParams, tab],
  );
  return {
    open: useCallback(() => {
      apply(true);
    }, [apply]),
    close: useCallback(() => {
      apply(false);
    }, [apply]),
  };
}
