import { ProjectList } from "./ProjectList";
import { ProjectView } from "./ProjectView";

/**
 * EDS · Проекты (SPEC-v3 §7.3 «Все проекты»): список `/eds/projects` или карточка `/eds/projects/:номер` (номер `ПР-2026-104`
 * или id сделки). Договор, акт и сканы — вкладки бокового окна карточки; источник данных — ERP.
 */
export function ProjectsScreen({ objectId }: { objectId?: string | undefined }) {
  return objectId ? <ProjectView objectId={objectId} /> : <ProjectList />;
}
