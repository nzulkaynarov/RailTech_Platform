/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** База API; пусто = same-origin (Caddy проксирует `/api/portal/*` на ERP). */
  readonly VITE_API_URL?: string;
  /** `1` — MSW-мок портального API (только dev). */
  readonly VITE_PORTAL_MOCK?: string;
  /** Имя клиентского бота CRM без @. */
  /** База CRM для формы «Я новый клиент» (`POST /api/v1/leads/web`); пусто вне dev — формы нет. */
  readonly VITE_CRM_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
