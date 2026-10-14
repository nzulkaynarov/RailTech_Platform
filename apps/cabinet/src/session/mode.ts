import { createContext, useContext } from 'react';

/**
 * Режим запуска: `miniapp` — внутри Telegram (есть `initData`), `web` — обычный браузер.
 * Определяется один раз при старте (App) и не меняется до перезагрузки.
 */
export type AppMode = 'miniapp' | 'web';

export const AppModeContext = createContext<AppMode>('web');

export function useAppMode(): AppMode {
  return useContext(AppModeContext);
}
