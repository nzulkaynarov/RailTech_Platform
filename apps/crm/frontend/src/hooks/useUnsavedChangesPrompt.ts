import { useContext, useEffect } from "react";
import { UNSAFE_NavigationContext as NavigationContext } from "react-router";

type Method = (...args: unknown[]) => unknown;

/** Подменить метод навигатора на время эффекта; вернуть функцию восстановления. */
function guard(target: object, name: "push" | "go", confirm: () => boolean): () => void {
  const original = Reflect.get(target, name) as Method;
  Reflect.set(target, name, (...args: unknown[]) => {
    if (confirm()) original.apply(target, args);
  });
  return () => {
    Reflect.set(target, name, original);
  };
}

/**
 * Предупреждение при уходе со страницы с несохранёнными изменениями: закрытие вкладки
 * (`beforeunload`) и переходы внутри CRM. `useBlocker` работает только с data router,
 * а приложение на `BrowserRouter`, поэтому — тот же приём, что у Refine
 * (`@refinedev/react-router` `UnsavedChangesNotifier`): перехват `navigator.push/go`.
 * Переходы с `replace` не перехватываются.
 */
export function useUnsavedChangesPrompt(message: string, when: boolean): void {
  const { navigator } = useContext(NavigationContext);

  useEffect(() => {
    if (!when) return;
    const onUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    const confirm = () => window.confirm(message);
    window.addEventListener("beforeunload", onUnload);
    const restore = [guard(navigator, "push", confirm), guard(navigator, "go", confirm)];
    return () => {
      window.removeEventListener("beforeunload", onUnload);
      restore.forEach((undo) => {
        undo();
      });
    };
  }, [navigator, message, when]);
}
