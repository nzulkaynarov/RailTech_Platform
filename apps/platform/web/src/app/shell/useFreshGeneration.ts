import { useState } from "react";
import { useLocation } from "react-router";

/**
 * Счётчик «открыть форму заново»: меню «Создать» шлёт при каждом выборе разовую метку `fresh` (`freshMark`), и только она
 * сбрасывает форму. Прочие смены адреса на странице (боковое окно, вкладки) введённое сохраняют — они подменяют адрес и
 * теряют `state`, поэтому метка запоминается здесь. Число добавляют в `key` формы.
 */
export function useFreshGeneration(): number {
  const location = useLocation();
  const fresh = (location.state as { fresh?: number } | null)?.fresh;
  const [seen, setSeen] = useState(fresh);
  const [generation, setGeneration] = useState(0);
  if (fresh !== undefined && fresh !== seen) {
    setSeen(fresh);
    setGeneration((value) => value + 1);
  }
  return generation;
}
