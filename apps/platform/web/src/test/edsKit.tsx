import { beforeEach } from "vitest";

import { resetEds } from "../mocks/fixtures/edsDocuments";
import { resetRoles } from "../mocks/fixtures/roles";
import { setupBotTests } from "./botKit";

export { panelEl, renderAt, signIn } from "./botKit";

/** Оснастка тестов «EDS · Документы»: чистые моки документов и ролей, ширина 1440, русский язык, ни одного пропущенного ключа. */
export function setupEdsTests(width = 1440): void {
  setupBotTests(width);
  beforeEach(() => {
    resetEds();
    resetRoles();
  });
}
