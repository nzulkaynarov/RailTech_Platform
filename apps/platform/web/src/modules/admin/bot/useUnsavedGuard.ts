import { App } from "antd";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useBlocker } from "react-router";

/**
 * Несохранённые изменения формы: при уходе с экрана или смене раздела настроек — вопрос «Выйти без сохранения?»,
 * при закрытии вкладки — предупреждение браузера. Смена панели и вкладки (`?panel=`, `?text=`) вопроса не вызывает.
 */
export function useUnsavedGuard(dirty: boolean): void {
  const { t } = useTranslation("bot");
  const { modal } = App.useApp();
  const blocker = useBlocker(({ currentLocation, nextLocation }) => {
    if (!dirty) return false;
    if (currentLocation.pathname !== nextLocation.pathname) return true;
    const section = (search: string) => new URLSearchParams(search).get("section");
    return section(currentLocation.search) !== section(nextLocation.search);
  });

  useEffect(() => {
    if (blocker.state !== "blocked") return;
    modal.confirm({
      title: t("guard.title"),
      content: t("guard.text"),
      okText: t("guard.leave"),
      cancelText: t("guard.stay"),
      okButtonProps: { danger: true },
      onOk: () => {
        blocker.proceed();
      },
      onCancel: () => {
        blocker.reset();
      },
    });
  }, [blocker, modal, t]);

  useEffect(() => {
    if (!dirty) return;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => {
      window.removeEventListener("beforeunload", handler);
    };
  }, [dirty]);
}
