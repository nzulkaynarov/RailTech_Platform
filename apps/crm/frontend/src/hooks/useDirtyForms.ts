import { useWarnAboutChange } from "@refinedev/core";
import { useCallback, useRef } from "react";

/**
 * Несколько форм на одной странице (мастер первого запуска): Refine предупреждает об уходе
 * (`UnsavedChangesNotifier`), пока не сохранена хотя бы одна из них. Одна форма вызывает
 * `useWarnAboutChange().setWarnWhen` сама.
 */
export function useDirtyForms(): (key: string, dirty: boolean) => void {
  const { setWarnWhen } = useWarnAboutChange();
  const dirty = useRef(new Set<string>());
  return useCallback(
    (key: string, isDirty: boolean) => {
      if (isDirty) dirty.current.add(key);
      else dirty.current.delete(key);
      setWarnWhen(dirty.current.size > 0);
    },
    [setWarnWhen],
  );
}
