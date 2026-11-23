import type { EdsRouteStep } from "../api/generated/model";
import type { HistoryItem } from "./History";

/** Точка шага маршрута на ленте: идёт — ждёт, не очередь — ещё не начато, остальное — сделано. */
export function routeStepState(status: EdsRouteStep["status"]): HistoryItem["state"] {
  if (status === "current") return "waiting";
  if (status === "pending") return "todo";
  return "done";
}
