import { useEffect, useState } from "react";
import { useLocation } from "react-router";

import { canEdit } from "../../app/access";
import { useAuth } from "../../app/auth/useAuth";
import { useBannerHidden } from "./hidden";
import { useSetupChecklist } from "./useSetupChecklist";

/**
 * Известно ли, нужен ли баннер «Настройка Платформы» (UX-1c, аудит 2026-10-30, S10). Пока чек-лист администратора не
 * ответил, рабочая область не показывается (`visibility: hidden`, экран уже грузит свои данные), чтобы баннер (~95 px)
 * не вставился над готовым экраном и не столкнул его вниз. Не администратору, при скрытом до завтра баннере и после
 * ответа (или сбоя — тогда баннера нет) — известно сразу. Запрос общий с баннером и пунктом меню (тот же кэш).
 * Предел ожидания — `SETUP_WAIT_MS`: чек-лист завис (медленный BFF или CRM, сеть) — экран показывается без него, а баннер,
 * если придёт позже, встаёт под экраном этого адреса, а не над ним (`useLateSetupBanner`, UX-2b): готовый экран не
 * сдвигается; со следующего перехода баннер — на своём месте сверху.
 */
export const SETUP_WAIT_MS = 800;

export function useSetupKnown(): boolean {
  const { me } = useAuth();
  const allowed = canEdit(me, "admin");
  const checklist = useSetupChecklist(allowed);
  const hidden = useBannerHidden(me.id);
  const [waited, setWaited] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setWaited(true);
    }, SETUP_WAIT_MS);
    return () => {
      window.clearTimeout(timer);
    };
  }, []);
  return !allowed || hidden || !checklist.isPending || waited;
}

const RELEASED = "\u0000released";

/**
 * Чек-лист ответил уже после показа экрана (`shown` — рабочая область видна, а чек-лист ещё грузится): на этом адресе баннер
 * ставится в конец рабочей области, чтобы не столкнуть готовый экран вниз (layout-shift, UX-2b — флейк «Мои задачи
 * администратора на 390»). После перехода на другой адрес баннер снова сверху, в том числе при возврате.
 */
export function useLateSetupBanner(shown: boolean): boolean {
  const { me } = useAuth();
  const { pathname } = useLocation();
  const allowed = canEdit(me, "admin");
  const checklist = useSetupChecklist(allowed);
  const hidden = useBannerHidden(me.id);
  const [latePath, setLatePath] = useState<string | null>(null);
  // Состояние от прошлых отрисовок (react.dev «storing information from previous renders»): адрес, на котором экран
  // показали без ответа чек-листа, и уход с него.
  if (latePath === null && shown && allowed && !hidden && checklist.isPending) {
    setLatePath(pathname);
  } else if (latePath !== null && latePath !== RELEASED && latePath !== pathname) {
    setLatePath(RELEASED);
  }
  return latePath === pathname;
}
