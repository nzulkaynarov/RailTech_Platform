import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { addCompany, pickCompany, searchCompany, selectedLabel } from "../../../test/fields";
import { renderUi } from "../../../test/renderUi";
import { server } from "../../../test/server";

import { CompanyPicker, type PickedCompany } from "./CompanyPicker";
import { PersonPicker } from "./PersonPicker";

function Harness({
  onChange,
  role,
}: {
  onChange: (company: PickedCompany | null) => void;
  role?: "supplier";
}) {
  const [value, setValue] = useState<PickedCompany | null>(null);
  return (
    <>
      <label htmlFor="co">Организация</label>
      <CompanyPicker
        id="co"
        value={value}
        role={role}
        onChange={(company) => {
          setValue(company);
          onChange(company);
        }}
      />
      <label htmlFor="pe">Человек</label>
      <PersonPicker id="pe" companyId={value?.id ?? ""} value="" onChange={() => undefined} />
    </>
  );
}

describe("CompanyPicker (ЕД-6)", () => {
  it("значение появляется только выбором строки: набранный текст компанией не становится", async () => {
    const picked: (PickedCompany | null)[] = [];
    renderUi(<Harness onChange={(c) => picked.push(c)} />);
    const field = screen.getByLabelText("Организация");
    searchCompany(field, "Путь");
    expect(picked).toEqual([]);
    await pickCompany(field, "Путь", "АО «Демо-Путь»");
    expect(picked).toHaveLength(1);
    expect(picked[0]).toMatchObject({ id: "7", name: "АО «Демо-Путь»", inn: "300000777" });
    expect(selectedLabel(field)).toBe("АО «Демо-Путь»");
  });

  it("в строке видны ИНН и роль, «Завести» — последняя строка; роль формы поднимает строку, но не прячет остальные", async () => {
    let asked: URLSearchParams | undefined;
    server.use(
      http.get("*/people/counterparties", ({ request }) => {
        asked = new URL(request.url).searchParams;
        return HttpResponse.json({
          items: [
            {
              id: "9",
              name: "ООО «Поставщик Север»",
              inn: null,
              country: "Узбекистан",
              roles: {
                client: false,
                supplier: true,
                manufacturer: false,
                partner: false,
                organization: false,
              },
              crm_client_id: null,
              email: null,
            },
          ],
        });
      }),
    );
    renderUi(<Harness onChange={() => undefined} role="supplier" />);
    searchCompany(screen.getByLabelText("Организация"), "Север");
    expect(await screen.findByText(/ИНН не указан · поставщик · Узбекистан/)).toBeInTheDocument();
    expect(await screen.findByText("Завести «Север»")).toBeInTheDocument();
    const rows = document.querySelectorAll(".ant-select-dropdown .ant-select-item-option");
    expect(rows[rows.length - 1]).toHaveTextContent("Завести «Север»");
    expect(asked?.get("role")).toBe("supplier");
    expect(asked?.get("q")).toBe("Север");
  });

  it("«Завести»: новая компания возвращается в поле; ИНН уже есть — берётся существующая, вторая не заводится", async () => {
    renderUi(<Harness onChange={() => undefined} />);
    const field = screen.getByLabelText("Организация");
    await addCompany(field, "Таможенный комитет", "200000123");
    expect(selectedLabel(field)).toBe("Таможенный комитет");
    // дубль по ИНН: показывается существующая компания
    await addCompany(field, "Другое имя", "300000777");
    await waitFor(() => {
      expect(selectedLabel(field)).toBe("АО «Демо-Путь»");
    });
    // вторая компания не заведена: по её названию в контрагентах пусто
    const found = (await (await fetch("/api/v1/people/counterparties?q=Другое")).json()) as {
      items: unknown[];
    };
    expect(found.items).toEqual([]);
    expect(screen.queryByRole("dialog", { name: "Новая компания" })).toBeNull();
  });

  it("короткий ИНН не отправляется: «Завести» недоступна", async () => {
    renderUi(<Harness onChange={() => undefined} />);
    searchCompany(screen.getByLabelText("Организация"), "Новая");
    fireEvent.click(await screen.findByText("Завести «Новая»"));
    const sheet = await screen.findByRole("dialog", { name: "Новая компания" });
    fireEvent.change(within(sheet).getByLabelText("ИНН"), { target: { value: "12" } });
    expect(within(sheet).getByRole("button", { name: "Завести" })).toBeDisabled();
  });
});
