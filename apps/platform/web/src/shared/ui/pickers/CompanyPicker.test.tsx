import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { addCompany, pickCompany, searchCompany, selectedLabel } from "../../../test/fields";
import { renderUi } from "../../../test/renderUi";
import { server } from "../../../test/server";

import { CompanyPicker, type PickedCompany, useApplyCompanyRole } from "./CompanyPicker";
import { PersonPicker } from "./PersonPicker";

function Harness({
  onChange,
  role,
  assignRole,
}: {
  onChange: (company: PickedCompany | null) => void;
  role?: "supplier";
  assignRole?: boolean;
}) {
  const [value, setValue] = useState<PickedCompany | null>(null);
  const [saved, setSaved] = useState(false);
  const [refused, setRefused] = useState<string | null>(null);
  const applyRole = useApplyCompanyRole();
  return (
    <>
      <label htmlFor="co">Организация</label>
      <CompanyPicker
        id="co"
        value={value}
        role={role}
        assignRole={assignRole}
        onChange={(company) => {
          setValue(company);
          onChange(company);
        }}
      />
      {/* «Сохранить» формы: роль ставится здесь, а не при выборе */}
      <button
        type="button"
        onClick={() => {
          setSaved(false);
          void applyRole(value).then((text) => {
            setRefused(text);
            setSaved(text === null);
          });
        }}
      >
        Сохранить
      </button>
      {refused ? <p role="alert">{refused}</p> : null}
      {saved ? <p>Сохранено</p> : null}
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

  it("без ИНН дубль по названию: берётся существующая компания, вторая не заводится", async () => {
    renderUi(<Harness onChange={() => undefined} />);
    const field = screen.getByLabelText("Организация");
    await addCompany(field, "гни мирабадского района");
    await waitFor(() => {
      expect(selectedLabel(field)).toBe("ГНИ Мирабадского района");
    });
    const found = (await (await fetch("/api/v1/people/counterparties?q=мирабадского")).json()) as {
      items: unknown[];
    };
    expect(found.items).toHaveLength(1);
  });

  it("ИНН у компании без роли, которой нет в поиске: берётся компания из ответа 409, тупика нет", async () => {
    const picked: (PickedCompany | null)[] = [];
    renderUi(<Harness onChange={(c) => picked.push(c)} />);
    const field = screen.getByLabelText("Организация");
    // в поиске её нет
    searchCompany(field, "Скрытая");
    expect(await screen.findByText("Завести «Скрытая»")).toBeInTheDocument();
    expect(screen.queryByText(/ИНН 300000999/)).toBeNull();
    await addCompany(field, "Скрытая копия", "300000999");
    await waitFor(() => {
      expect(selectedLabel(field)).toBe("ООО «Скрытая Компания»");
    });
    expect(picked).toHaveLength(1);
    expect(picked[0]).toMatchObject({ id: "14", inn: "300000999", country: "Узбекистан" });
    expect(screen.queryByRole("dialog", { name: "Новая компания" })).toBeNull();
    expect(screen.queryByText(/в списке выбора её нет/)).toBeNull();
  });

  it("ответ 409 без строки компании и без неё в поиске: понятный отказ, поле остаётся пустым", async () => {
    server.use(
      http.post("*/people/counterparties", () =>
        HttpResponse.json(
          {
            code: "CONFLICT",
            message: "Такая компания уже есть.",
            source: "erp",
            details: { reason: "company_exists", existing_id: "999" },
          },
          { status: 409 },
        ),
      ),
    );
    const picked: (PickedCompany | null)[] = [];
    renderUi(<Harness onChange={(c) => picked.push(c)} />);
    const field = screen.getByLabelText("Организация");
    searchCompany(field, "Скрытая");
    fireEvent.click(await screen.findByText("Завести «Скрытая»"));
    const sheet = await screen.findByRole("dialog", { name: "Новая компания" });
    fireEvent.click(within(sheet).getByRole("button", { name: "Завести" }));
    expect(await within(sheet).findByText(/в списке выбора её нет/)).toBeVisible();
    expect(picked).toEqual([]);
  });

  it("форме нужна роль поставщика: выбор ничего не пишет, роль ставится при сохранении и только компании без неё", async () => {
    const marked: { id: string; body: unknown }[] = [];
    server.use(
      http.post("*/people/counterparties/:id/roles", async ({ params, request }) => {
        marked.push({ id: String(params["id"]), body: await request.json() });
        return HttpResponse.json({});
      }),
    );
    const picked: (PickedCompany | null)[] = [];
    renderUi(<Harness onChange={(c) => picked.push(c)} role="supplier" assignRole />);
    const field = screen.getByLabelText("Организация");
    await pickCompany(field, "Путь", "АО «Демо-Путь»");
    expect(picked[0]).toMatchObject({ id: "7", pendingRole: "supplier" });
    // форму не сохранили — роли нет (факт «заказ создан» ещё не случился)
    expect(marked).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(marked).toEqual([{ id: "7", body: { role: "supplier", on: true } }]);
    });
    // у «Поставщик Север» роль уже есть — отметки нет ни при выборе, ни при сохранении
    await pickCompany(field, "Север", "ООО «Поставщик Север»");
    expect(picked[1]?.pendingRole).toBeUndefined();
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await screen.findByText("Сохранено");
    expect(marked).toHaveLength(1);
  });

  it.each([
    [403, /Не удалось отметить компанию поставщиком: нет права/],
    [404, /Компании нет в списке контрагентов/],
    [503, /Не удалось отметить роль компании\. Повторите/],
  ])(
    "роль не поставилась (HTTP %i): причина берётся из факта, «нет права» — только при 403",
    async (status, text) => {
      server.use(
        http.post("*/people/counterparties/:id/roles", () =>
          HttpResponse.json({ code: "X", message: "Сбой.", source: "erp" }, { status }),
        ),
      );
      renderUi(<Harness onChange={() => undefined} role="supplier" assignRole />);
      const field = screen.getByLabelText("Организация");
      await pickCompany(field, "Путь", "АО «Демо-Путь»");
      fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(text);
      if (status !== 403) expect(screen.queryByText(/нет права/)).toBeNull();
      expect(screen.queryByText("Сохранено")).toBeNull();
    },
  );

  it("короткий ИНН не отправляется: «Завести» недоступна", async () => {
    renderUi(<Harness onChange={() => undefined} />);
    searchCompany(screen.getByLabelText("Организация"), "Новая");
    fireEvent.click(await screen.findByText("Завести «Новая»"));
    const sheet = await screen.findByRole("dialog", { name: "Новая компания" });
    fireEvent.change(within(sheet).getByLabelText("ИНН"), { target: { value: "12" } });
    expect(within(sheet).getByRole("button", { name: "Завести" })).toBeDisabled();
  });
});
