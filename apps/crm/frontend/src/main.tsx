import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App";
import { ensureLiveRegion } from "./app/liveRegion";
import { applyTagColors } from "./app/theme";
import "./pages/pages.css";
import "./styles/a11y.css";

const root = document.getElementById("root");
if (!root) {
  throw new Error("#root element not found");
}

// Live-регион должен быть в DOM до первого тоста, иначе первый не озвучивается.
ensureLiveRegion();
applyTagColors();

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
