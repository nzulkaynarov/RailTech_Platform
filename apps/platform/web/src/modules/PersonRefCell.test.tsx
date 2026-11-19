import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { signIn } from "../test/edsKit";
import { renderUi } from "../test/renderUi";
import { PersonRefCell } from "./PersonRefCell";

describe("PersonRefCell (СУЩ-3)", () => {
  it("должность — из справочника сотрудников по id ссылки", async () => {
    signIn("manager@demo.example");
    renderUi(<PersonRefCell person={{ id: "u-demo-director", name: "Демо Директоров" }} />);
    expect(screen.getByText("Демо Директоров")).toBeVisible();
    expect(await screen.findByText("Директор")).toBeVisible();
  });

  it("человека нет в справочнике — инициалы и имя из ссылки; своя подпись заменяет должность", async () => {
    signIn("manager@demo.example");
    renderUi(
      <>
        <PersonRefCell person={{ id: "nobody", name: "Гость Системы" }} />
        <PersonRefCell
          person={{ id: "u-demo-director", name: "Демо Директоров" }}
          caption="подписал"
        />
      </>,
    );
    expect(screen.getByText("Гость Системы")).toBeVisible();
    expect(screen.getByText("ГС")).toBeInTheDocument();
    expect(await screen.findByText("подписал")).toBeVisible();
    expect(screen.queryByText("Директор")).toBeNull();
  });
});
