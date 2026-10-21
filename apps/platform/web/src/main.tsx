import "@fontsource-variable/inter";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App";
import "./shared/i18n";
import "./styles/global.css";

const root = document.getElementById("root");
if (!root) {
  throw new Error("#root element not found");
}

/** `pnpm dev:mock`: API Платформы отвечает MSW (моки orval), BFF не нужен. Только dev. */
async function enableMocking(): Promise<void> {
  if (import.meta.env.DEV && import.meta.env.VITE_API_MOCKING === "true") {
    const { worker } = await import("./mocks/browser");
    await worker.start({ onUnhandledFrame: "bypass", quiet: true });
  }
}

void enableMocking().then(() => {
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
});
