import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import './i18n';
import './index.css';
import { App } from './app/App';
import { initialPath } from './telegram/start-param';
import { initMiniApp } from './telegram/theme';
import { getStartParam, getTelegramWebApp, isMiniApp } from './telegram/webapp';

async function bootstrap(): Promise<void> {
  // Мок портального API — только dev-сборка с VITE_PORTAL_MOCK=1; в прод-сборку ветка не попадает.
  if (import.meta.env.DEV && import.meta.env.VITE_PORTAL_MOCK === '1') {
    const { startPortalMock } = await import('./mocks/browser');
    await startPortalMock();
  }
  const webApp = getTelegramWebApp();
  if (webApp && isMiniApp()) {
    initMiniApp(webApp);
    // Deep-link из кнопки бота: `start_param=deal_42` → /deals/42 до первого рендера.
    const target = initialPath(window.location.pathname, getStartParam());
    if (target !== window.location.pathname) window.history.replaceState(null, '', target);
  }

  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

void bootstrap();
