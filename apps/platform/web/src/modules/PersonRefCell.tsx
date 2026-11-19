import type { PersonRef } from "../shared/api/generated/model";
import { useListStaffDirectory } from "../shared/api/generated/platform-bff";
import { PersonCell } from "../shared/ui/EntityCell";

/** Справочник меняется редко: один запрос на сеанс работы, а не на строку (СУЩ-3). */
const DIRECTORY_STALE_MS = 10 * 60 * 1000;

/**
 * Сотрудник в строке «кто сделал» (СУЩ-3, `ui-standard.md` §12): фото или инициалы, ФИО как в записи, второй строкой —
 * должность. Ссылка несёт только id и имя; фото и должность — из справочника сотрудников по id. Справочник не загрузился
 * или человека в нём нет — инициалы и имя из ссылки.
 */
export function PersonRefCell({
  person,
  caption,
  size,
}: {
  person: Pick<PersonRef, "id" | "name">;
  /** Своя вторая строка (роль в документе) вместо должности */
  caption?: string | null;
  size?: 24 | 32 | 40;
}) {
  const directory = useListStaffDirectory({ query: { staleTime: DIRECTORY_STALE_MS } });
  const card = directory.data?.items.find((item) => item.id === person.id);
  return (
    <PersonCell
      name={person.name}
      caption={caption === undefined ? (card?.position ?? null) : caption}
      photoUrl={card?.avatar_url ?? null}
      {...(size ? { size } : {})}
    />
  );
}
