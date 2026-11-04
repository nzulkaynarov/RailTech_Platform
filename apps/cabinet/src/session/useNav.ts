import { useMemo } from "react";

import { navFor, type Nav } from "@/app/nav";
import { useMe } from "./useMe";

/** Меню текущей сессии: разделы из `/me.modules` (ADR-0022). До загрузки сессии — пустое. */
export function useNav(): Nav {
  const modules = useMe().data?.modules;
  return useMemo(() => navFor(modules), [modules]);
}
