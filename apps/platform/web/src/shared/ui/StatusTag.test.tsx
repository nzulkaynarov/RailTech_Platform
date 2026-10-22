import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { STATUS_KINDS, STATUS_TONE } from "../lib/statuses";
import { renderUi } from "../../test/renderUi";
import { StatusTag } from "./StatusTag";

describe("StatusTag", () => {
  it("статус — слово из словаря, а не код и не один цвет", () => {
    renderUi(<StatusTag kind="invoice" status="proof_received" />);
    const tag = screen.getByText("Платёжка получена");
    expect(tag).toBeVisible();
    expect(tag.closest(".ant-tag")).toHaveAttribute("data-tone", "gold");
    expect(screen.queryByText("proof_received")).toBeNull();
  });

  it("цвет текста — из колонки «текст», фон и рамка светлые", () => {
    renderUi(<StatusTag kind="invoice" status="paid" />);
    const tag = screen.getByText("Оплачен").closest<HTMLElement>(".ant-tag");
    expect(tag).toHaveStyle({
      color: "#237804",
      backgroundColor: "#f6ffed",
      borderColor: "#b7eb8f",
    });
  });

  it("у каждого статуса каждого документа есть непустое слово на трёх языках", () => {
    for (const language of ["ru", "uz", "en"]) {
      for (const kind of STATUS_KINDS) {
        for (const status of Object.keys(STATUS_TONE[kind])) {
          const { container, unmount } = renderUi(<StatusTag kind={kind} status={status} />, {
            language,
          });
          const text = container.querySelector(".ant-tag")?.textContent ?? "";
          expect(text.trim(), `${language}:${kind}:${status}`).not.toBe("");
          expect(text, `${language}:${kind}:${status}`).not.toContain("status.");
          unmount();
        }
      }
    }
  });

  it("слово по языку интерфейса", () => {
    renderUi(<StatusTag kind="quote" status="accepted" />, { language: "en" });
    expect(screen.getByText("Accepted by client")).toBeVisible();
  });

  it("своё слово вместо словарного: «Черновик · отправка заблокирована»", () => {
    renderUi(
      <StatusTag kind="quote" status="draft">
        Черновик · отправка заблокирована
      </StatusTag>,
    );
    expect(screen.getByText("Черновик · отправка заблокирована")).toBeVisible();
  });

  it("произвольный тег и неизвестный код", () => {
    renderUi(
      <>
        <StatusTag tone="red">срок сегодня</StatusTag>
        <StatusTag kind="contract" status="неизвестный" />
      </>,
    );
    expect(screen.getByText("срок сегодня").closest(".ant-tag")).toHaveAttribute(
      "data-tone",
      "red",
    );
    expect(screen.getByText("неизвестный").closest(".ant-tag")).toHaveAttribute(
      "data-tone",
      "default",
    );
  });
});
