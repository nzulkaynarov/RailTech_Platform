import { useState } from "react";
import { RouterProvider, createBrowserRouter } from "react-router";

import { AppProviders } from "./providers";
import { routes } from "./router";

export function App() {
  const [router] = useState(() => createBrowserRouter(routes));
  return (
    <AppProviders>
      <RouterProvider router={router} />
    </AppProviders>
  );
}
