/** Переход в этой же вкладке; отдельной функцией, чтобы тесты подменяли его (`window.location` в jsdom не подменить). */
export function navigateTo(url: string): void {
  window.location.assign(url);
}
