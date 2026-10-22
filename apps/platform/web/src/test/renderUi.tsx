import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router";

import { AppProviders } from "../app/providers";
import i18n from "../shared/i18n";

/** Рендер общего компонента с темой antd, i18n и роутером (ссылки `Link`/`LinkButton`); язык — русский, как по умолчанию. */
export function renderUi(ui: ReactElement, options: { route?: string; language?: string } = {}) {
  void i18n.changeLanguage(options.language ?? "ru");
  return render(
    <AppProviders>
      <MemoryRouter initialEntries={[options.route ?? "/"]}>{ui}</MemoryRouter>
    </AppProviders>,
  );
}
