import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";

/** Доступ «чтение» к разделу `company.settings`: просмотр и предпросмотры можно, изменять нельзя. */
export function useReadOnly(): boolean {
  const { me } = useAuth();
  return !canEdit(me, "company.settings");
}
