import { useEffect, useState } from "react";

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
 * если придёт позже, вставится одним сдвигом (допустимое исключение, решение архитектора по UX-1c).
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
