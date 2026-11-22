/**
 * «Подписал» follows the chosen person: it is replaced while empty or still equal to the name put in by the previous
 * choice, and cleared when the person goes (`name` null). A name typed by hand is never touched.
 */
export function signedByAfter(current: string, auto: string, name: string | null): string {
  const own = current.trim() === "" || (auto !== "" && current === auto);
  if (!own) return current;
  return name ?? "";
}
