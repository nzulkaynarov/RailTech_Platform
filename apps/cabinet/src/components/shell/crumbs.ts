import { createContext, useContext, useEffect, type Dispatch, type SetStateAction } from 'react';
import { useLocation } from 'react-router-dom';

/**
 * Последняя крошка пути — номер документа из данных, которые экран уже загрузил (CAB-FIX-2, K14): KP-2026-0042,
 * D-2026-0048, Z-…; оболочка своих запросов ради крошек не делает. Крошка привязана к адресу: чужая (от прошлого
 * экрана) не показывается.
 */
export interface PageCrumb {
  path: string;
  label: string;
}

export const SetCrumbContext = createContext<Dispatch<SetStateAction<PageCrumb | null>> | null>(null);

/** Экран сообщает оболочке номер своего документа; `null` — данных ещё нет (крошка — тип документа без номера). */
export function usePageCrumb(label: string | null | undefined): void {
  const setCrumb = useContext(SetCrumbContext);
  const { pathname } = useLocation();
  useEffect(() => {
    if (!setCrumb || !label) return;
    setCrumb({ path: pathname, label });
    return () => setCrumb((current) => (current?.path === pathname && current.label === label ? null : current));
  }, [setCrumb, label, pathname]);
}
