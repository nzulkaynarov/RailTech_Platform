/** Тема и общие опции графиков `@ant-design/plots` из токенов antd (светлая/тёмная — по фону). */
import { theme as antdTheme } from "antd";

import { isDarkColor } from "../../domain/dashboardCharts";

export const CHART_HEIGHT = 220;

/** Без подписей осей: заголовок карточки уже говорит, что на графике. */
export const AXES = { x: { title: false }, y: { title: false } } as const;
export const LEGEND_TOP = { color: { position: "top" } } as const;

export function useChartTheme() {
  const { token } = antdTheme.useToken();
  const palette = [
    token.colorPrimary,
    token.colorWarning,
    token.colorSuccess,
    token.purple7,
    token.cyan7,
    token.magenta7,
    token.colorError,
    token.geekblue4,
  ];
  return {
    token,
    palette,
    theme: {
      type: isDarkColor(token.colorBgContainer) ? "classicDark" : "classic",
      color: token.colorPrimary,
      category10: palette,
    },
  };
}
