/**
 * Live-регион для тостов antd `message` (WCAG 4.1.3): в antd 5 у сообщений нет
 * `role`/`aria-live`, поэтому контейнер сообщений — постоянный `role="status"`.
 * Регион создаётся до первого сообщения (иначе первое не озвучивается).
 */
const ID = "app-live-region";

export function ensureLiveRegion(): HTMLElement {
  const existing = document.getElementById(ID);
  if (existing) return existing;
  const region = document.createElement("div");
  region.id = ID;
  region.setAttribute("role", "status");
  region.setAttribute("aria-live", "polite");
  document.body.appendChild(region);
  return region;
}
