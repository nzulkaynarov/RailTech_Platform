import { toast as sonner } from 'sonner';

/**
 * Тосты Cabinet. Идентификатор тоста — его вид и текст: повторное то же сообщение (двойной клик, повтор действия)
 * заменяет показанный тост, а не складывает стопку; разные сообщения не затирают друг друга.
 */
const show = (kind: 'success' | 'error' | 'info') => (message: string) =>
  sonner[kind](message, { id: `${kind}:${message}` });

export const toast = {
  success: show('success'),
  error: show('error'),
  info: show('info'),
  dismiss: () => sonner.dismiss(),
};
