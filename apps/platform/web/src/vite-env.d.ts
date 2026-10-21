/// <reference types="vite/client" />
/// <reference types="msw/vite/client" />

interface ImportMetaEnv {
  /** `true` в `vite --mode mock`: API отвечает MSW, BFF не нужен. */
  readonly VITE_API_MOCKING?: string;
}
