/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** База API; пусто = same-origin (Caddy проксирует `/api/portal/*` на ERP). */
  readonly VITE_API_URL?: string;
  /** `1` — MSW-мок портального API (только dev). */
  readonly VITE_PORTAL_MOCK?: string;
  /** Имя клиентского бота CRM без @. */
  readonly VITE_BOT_USERNAME?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
