import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import type { ProjectCard } from "../../../shared/api/generated/model";
import { getGetEdsProjectQueryKey } from "../../../shared/api/generated/platform-bff";
import { projectRef } from "./api";

/**
 * После действия по договору или акту BFF отдаёт обновлённую карточку проекта: она кладётся в кэш (экран и обе вкладки
 * видят новый статус сразу), списки проектов и реестр «Все документы» перезапрашиваются — статус там меняется тоже.
 */
export function useApplyCard(objectId: string): (card: ProjectCard) => void {
  const client = useQueryClient();
  return useCallback(
    (card: ProjectCard) => {
      client.setQueryData(getGetEdsProjectQueryKey(projectRef(objectId)), card);
      void client.invalidateQueries({
        predicate: (query) => {
          const head = query.queryKey[0];
          return head === "/api/v1/eds/projects" || head === "/api/v1/eds/documents";
        },
      });
    },
    [client, objectId],
  );
}
