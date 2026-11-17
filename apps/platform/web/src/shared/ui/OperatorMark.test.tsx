import { screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { renderUi } from "../../test/renderUi";
import { server } from "../../test/server";
import { OperatorMark } from "./OperatorMark";

const SVG =
  '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"><rect width="8" height="8"/></svg>';

describe("OperatorMark (ДВ-3)", () => {
  it("логотип своей компании из GET /setup/logo", async () => {
    server.use(
      http.get(
        "*/setup/logo",
        () => new HttpResponse(SVG, { headers: { "Content-Type": "image/svg+xml" } }),
      ),
    );
    const { container } = renderUi(<OperatorMark />);
    await waitFor(() => {
      expect(container.querySelector("img")?.getAttribute("src")).toMatch(/^blob:/);
    });
  });

  it("нет логотипа — буквы названия", async () => {
    const { container } = renderUi(<OperatorMark />);
    expect(await screen.findByText(/^[A-ZА-Я]{2}$/)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });
});
