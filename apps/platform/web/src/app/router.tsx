import type { RouteObject } from "react-router";

import { ScaffoldPage } from "../modules/dashboard/ScaffoldPage";

/** Карта маршрутов P0: одна страница-заглушка. Каркас AppShell и модули — фаза P1 (05-plan.md). */
export const routes: RouteObject[] = [{ path: "/", element: <ScaffoldPage /> }];
