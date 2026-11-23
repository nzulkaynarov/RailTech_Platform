/**
 * Отказ принять оферту и политику (ДВ-5): человек вышел, и экран входа объясняет почему. Выход очищает сессию и сам
 * отправляет на `/login` (`RequireSession`), поэтому причина передаётся не состоянием перехода, а отметкой на одну
 * загрузку экрана. Хранилище недоступно — отметка живёт в памяти вкладки.
 */
const KEY = 'rt-cab-legal-declined';
let inMemory = false;

export function rememberLegalDecline(): void {
  inMemory = true;
  try {
    sessionStorage.setItem(KEY, '1');
  } catch {
    // нет хранилища — отметка в памяти
  }
}

/** Есть ли отметка. Читает, не сбрасывая: инициализатор состояния React в StrictMode вызывается дважды. */
export function peekLegalDecline(): boolean {
  try {
    return sessionStorage.getItem(KEY) === '1' || inMemory;
  } catch {
    return inMemory;
  }
}

/** Сбросить отметку: объяснение показывается один раз (вызывается после показа). */
export function clearLegalDecline(): void {
  inMemory = false;
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    // нет хранилища
  }
}
