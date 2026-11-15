import { LinkButton } from "./LinkButton";
import { ChevronRightIcon } from "./icons";
import "./data-block.css";

/**
 * Переход к странице объекта из строки таблицы (стандарт интерфейса §7): стрелка «›» вместо кнопки «Открыть» в рамке в
 * каждой строке. Настоящая ссылка (открывается и в новой вкладке); имя для читалки экрана — `label`.
 */
export function RowOpenLink({ to, label, title }: { to: string; label: string; title: string }) {
  return (
    <LinkButton
      type="text"
      size="small"
      className="pf-row-open"
      icon={<ChevronRightIcon />}
      to={to}
      title={title}
      aria-label={label}
    />
  );
}
