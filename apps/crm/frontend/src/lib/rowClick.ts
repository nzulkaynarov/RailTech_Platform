/** Клик по строке открывает сводку, но не перехватывает клики по ссылкам и кнопкам внутри неё. */
export function isRowClick(target: EventTarget | null): boolean {
  return !(target instanceof Element && target.closest("a, button, input, label"));
}
