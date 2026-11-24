import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createQueryClient } from "../../../app/queryClient";
import { HttpResponse, http } from "msw";
import { RouterProvider, createMemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { AppProviders } from "../../../app/providers";
import { routes } from "../../../app/router";
import { usePanelsStore } from "../../../app/shell/panelsStore";
import { readEmployees, writeEmployees } from "../../../mocks/fixtures/employees";
import { findUser } from "../../../mocks/fixtures/users";
import { patchProfile } from "../../../mocks/profileStore";
import { buildMe, endSession, readSession, startSession } from "../../../mocks/mockSession";
import i18n from "../../../shared/i18n";
import { server } from "../../../test/server";
import { setViewportWidth } from "../../../test/viewport";
import { ROLE_ID, ref } from "../../../test/roles";

function renderAt(path: string) {
  const queryClient = createQueryClient({ retry: false, staleTime: 0 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <AppProviders queryClient={queryClient}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return { router, queryClient };
}

function signIn(email: string) {
  const user = findUser(email);
  if (!user) throw new Error(`нет демо-пользователя ${email}`);
  startSession(user);
}

beforeEach(() => {
  window.localStorage.clear();
  usePanelsStore.setState({ entries: {} });
  setViewportWidth(1440);
  void i18n.changeLanguage("ru");
});
afterEach(() => {
  endSession();
});

/** Боковое окно появляется после загрузки профиля и маршрута — ждём его, а не берём сразу. */
async function panelEl(): Promise<HTMLElement> {
  return waitFor(() => {
    const element = document.getElementById("pf-context-panel");
    if (!element) throw new Error("боковое окно ещё не появилось");
    return element;
  });
}

describe("Admin · Оргструктура (экран целиком на MSW)", () => {
  it("админ видит всех сотрудников; пока никто не выбран, в боковом окне — подсказка", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/org?panel=open");

    expect(await screen.findByRole("heading", { level: 1, name: "Сотрудники" })).toBeVisible();
    expect(
      await screen.findByRole("link", { name: "Открыть карточку: Демо Менеджеров" }),
    ).toBeVisible();
    expect(screen.getByText("Сотрудников: 10")).toBeVisible();
    const row = screen.getByRole("row", { name: /Демо Новичков/ });
    expect(within(row).getByText("Приглашён")).toBeVisible();
    expect(
      within(screen.getByRole("row", { name: /Демо Отключённый/ })).getByText("Отключён"),
    ).toBeVisible();
    expect(await within(await panelEl()).findByText("Объект не выбран")).toBeVisible();
  });

  it("фото сотрудников (СУЩ-3): в таблице круг с фото из профиля, у отключённого и без фото — инициалы", async () => {
    // фото загружено в «Профиле»: и у действующего, и у отключённого — отключённому BFF его не отдаёт
    patchProfile("u-demo-manager", { avatar: "x", avatarVersion: 3 });
    patchProfile("u-demo-disabled", { avatar: "x", avatarVersion: 4 });
    signIn("admin@demo.example");
    renderAt("/admin/org");

    const row = await screen.findByRole("row", { name: /Демо Менеджеров/ });
    expect(row.querySelector("img")).toHaveAttribute(
      "src",
      "/api/v1/staff/u-demo-manager/avatar?v=3",
    );
    expect(screen.getByRole("row", { name: /Демо Отключённый/ }).querySelector("img")).toBeNull();
    expect(screen.getByRole("row", { name: /Демо Новичков/ }).querySelector("img")).toBeNull();
  });

  it("«выдаётся» сменяется на «ок» без перезагрузки: список перечитывается, пока ERP не ответила (СЦ-8)", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/org");

    const row = await screen.findByRole("row", { name: /Демо Приглашённая/ });
    expect(within(row).getByText("Доступ выдаётся")).toBeVisible();

    await waitFor(
      () => {
        const next = screen.getByRole("row", { name: /Демо Приглашённая/ });
        expect(within(next).queryByText("Доступ выдаётся")).toBeNull();
        expect(within(next).queryByText("Доступ выдаётся")).toBeNull();
        expect(within(next).queryByText("Доступ не выдан")).toBeNull();
      },
      { timeout: 7000 },
    );
  }, 12000);

  it("сбой без текста: «Доступ не выдан.» и «Повторить», который вызывает маршрут", async () => {
    signIn("admin@demo.example");
    writeEmployees(
      readEmployees().map((e) =>
        e.id === "u-demo-manager" ? { ...e, erp_sync: "error" as const } : e,
      ),
    );
    renderAt("/admin/org?employee=u-demo-manager&panel=open");

    const panel = await panelEl();
    expect(await within(panel).findByText("Доступ не выдан.")).toBeVisible();
    fireEvent.click(within(panel).getByRole("button", { name: "Повторить" }));

    await waitFor(() => {
      expect(readEmployees().find((e) => e.id === "u-demo-manager")?.erp_sync).not.toBe("error");
    });
  });

  it.each([
    [
      "erp_provision_user: erp_not_configured: ERP не подключена — укажите адрес",
      "нет связи по настройкам подключения",
    ],
    ["erp_provision_user: erp_unauthorized: HTTP 401", "нет связи по настройкам подключения"],
    ["erp_provision_user: erp_unavailable: timeout", "раздел не ответил"],
    ["erp_provision_user: erp_email_conflict: busy", "учётная запись не принята"],
    ["provision: задача не поставлена в очередь", "не поставилась в очередь"],
  ])(
    "сбой с текстом CRM «%s»: причина словами, кода и текста сервера на экране нет",
    async (error, phrase) => {
      signIn("admin@demo.example");
      writeEmployees(
        readEmployees().map((e) =>
          e.id === "u-demo-manager"
            ? { ...e, erp_sync: "error" as const, erp_sync_error: error }
            : e,
        ),
      );
      renderAt("/admin/org?employee=u-demo-manager&panel=open");

      const panel = await panelEl();
      expect(await within(panel).findByText(new RegExp(phrase))).toBeVisible();
      expect(panel.textContent).not.toContain("erp_provision_user");
      expect(panel.textContent).not.toContain("erp_unavailable");
      expect(panel.textContent).not.toContain("busy");
    },
  );

  it("у отключённого нет метки «выдаётся» и «ERP», хотя роль с доступом сохранилась", async () => {
    signIn("admin@demo.example");
    writeEmployees(
      readEmployees().map((e) =>
        e.name === "Демо Отключённый" ? { ...e, erp_sync: "pending" as const } : e,
      ),
    );
    renderAt("/admin/org");

    const row = await screen.findByRole("row", { name: /Демо Отключённый/ });
    expect(within(row).queryByText("Доступ выдаётся")).toBeNull();
    expect(within(row).queryByText("Доступ не выдан")).toBeNull();
  });

  it("карточка открывается из адреса и по клику на имя", async () => {
    signIn("admin@demo.example");
    const { router } = renderAt("/admin/org");

    fireEvent.click(await screen.findByRole("link", { name: "Открыть карточку: Демо Менеджеров" }));

    expect(
      await within(await panelEl()).findByRole("heading", { level: 3, name: "Демо Менеджеров" }),
    ).toBeVisible();
    expect(router.state.location.search).toContain("employee=u-demo-manager");
    expect(router.state.location.search).toContain("panel=open");
    expect(
      await within(await panelEl()).findByRole("checkbox", { name: /^Менеджер(?!-)/ }),
    ).toBeChecked();
  });

  it("выдача роли: список и сохранённые роли меняются, при следующем входе — модули по матрице", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/org?employee=u-demo-manager&panel=open");
    await within(await panelEl()).findByRole("heading", { level: 3, name: "Демо Менеджеров" });

    fireEvent.click(
      await within(await panelEl()).findByRole("checkbox", { name: /^Менеджер(?!-)/ }),
    );
    fireEvent.click(within(await panelEl()).getByRole("checkbox", { name: /^Директор/ }));
    fireEvent.click(within(await panelEl()).getByRole("button", { name: "Сохранить роли" }));

    await waitFor(() => {
      expect(
        within(screen.getByRole("row", { name: /Демо Менеджеров/ })).getByText("Директор"),
      ).toBeVisible();
    });
    expect(readEmployees().find((e) => e.id === "u-demo-manager")?.role_ids).toEqual([
      ROLE_ID.DIRECTOR,
    ]);
    // тот же сотрудник входит позже: профиль мока считается по выданным ролям и матрице
    endSession();
    signIn("manager@demo.example");
    const me = buildMe(
      readSession() ?? { userId: "", activeRole: null, language: "ru", mustChangePassword: false },
    );
    expect(me?.roles).toEqual([ref("DIRECTOR")]);
    expect(me?.resources["erp.calc"]).toBe("full");
    expect(me?.modules).toContain("admin");
  });

  it("включённый после отключения, с ещё временным паролем, снова «Приглашён»", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/org?employee=u-demo-new&panel=open");
    const side = await panelEl();
    await within(side).findByRole("heading", { level: 3, name: "Демо Новичков" });

    fireEvent.click(within(side).getByRole("button", { name: "Отключить сотрудника" }));
    fireEvent.click(within(side).getByRole("button", { name: "Отключить" }));
    await within(side).findByText(/Сотрудник отключён и не может войти/);
    expect(
      within(screen.getByRole("row", { name: /Демо Новичков/ })).getByText("Отключён"),
    ).toBeVisible();

    fireEvent.click(within(side).getByRole("button", { name: "Включить сотрудника" }));
    fireEvent.click(within(side).getByRole("button", { name: "Включить" }));
    await waitFor(() => {
      expect(
        within(screen.getByRole("row", { name: /Демо Новичков/ })).getByText("Приглашён"),
      ).toBeVisible();
    });
  });

  it("директор читает, но не меняет: ни приглашения, ни флажков", async () => {
    signIn("director@demo.example");
    renderAt("/admin/org?employee=u-demo-manager&panel=open");

    await within(await panelEl()).findByRole("heading", { level: 3, name: "Демо Менеджеров" });
    expect(screen.queryByRole("button", { name: "Пригласить сотрудника" })).toBeNull();
    expect(within(await panelEl()).queryAllByRole("checkbox")).toHaveLength(0);
    expect(within(await panelEl()).queryByRole("button", { name: "Сохранить роли" })).toBeNull();
  });

  it("сотрудник без раздела Admin видит «Нет доступа»", async () => {
    signIn("supply@demo.example");
    renderAt("/admin/org");

    expect(await screen.findByRole("heading", { level: 1, name: "Нет доступа" })).toBeVisible();
    expect(screen.queryByRole("link", { name: /Открыть карточку/ })).toBeNull();
  });

  it("поиск и фильтр по статусу; ничего не найдено — слова и «Сбросить фильтры»", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/org");
    await screen.findByRole("link", { name: "Открыть карточку: Демо Менеджеров" });

    const search = screen.getByRole("combobox", { name: "Статус" });
    fireEvent.mouseDown(search);
    fireEvent.click(await screen.findByTitle("Приглашён"));
    await waitFor(() => {
      expect(screen.getByText("Сотрудников: 2")).toBeVisible();
    });

    fireEvent.change(screen.getByRole("searchbox", { name: "Поиск по сотрудникам" }), {
      target: { value: "zzz" },
    });
    expect(
      await screen.findByRole("heading", { level: 2, name: "Никого не найдено" }),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Сбросить фильтры" }));
    expect(await screen.findByText("Сотрудников: 10")).toBeVisible();
  });

  it("неизвестный сотрудник в адресе — «Сотрудник не найден» в боковом окне", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/org?employee=u-missing&panel=open");

    expect(await within(await panelEl()).findByText("Сотрудник не найден")).toBeVisible();
  });

  it("список не загрузился — слова и «Повторить»", async () => {
    signIn("admin@demo.example");
    server.use(
      http.get("*/admin/users", () =>
        HttpResponse.json(
          { code: "BACKEND_UNAVAILABLE", message: "x", source: "crm" },
          { status: 503 },
        ),
      ),
    );
    renderAt("/admin/org");

    expect(
      await screen.findByRole("heading", { level: 2, name: "Не удалось загрузить сотрудников" }),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Повторить" })).toBeVisible();
  });

  it("форма приглашения открывается по ?invite=open у админа и не открывается у директора", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/org?invite=open&panel=open");
    expect(
      await within(await panelEl()).findByRole("heading", {
        level: 3,
        name: "Пригласить сотрудника",
      }),
    ).toBeVisible();
    endSession();
  });

  it("повторное «Пригласить сотрудника» открывает пустую форму (QA-P1-D-3)", async () => {
    signIn("admin@demo.example");
    const { router } = renderAt("/admin/org?invite=open&panel=open");
    const panel = await panelEl();
    fireEvent.change(await within(panel).findByLabelText("Имя и фамилия"), {
      target: { value: "Черновик Приглашения" },
    });
    fireEvent.click(within(panel).getByRole("checkbox", { name: /^Директор/ }));
    expect(within(panel).getByLabelText("Имя и фамилия")).toHaveValue("Черновик Приглашения");

    await router.navigate("/admin/org?invite=open&panel=open");

    await waitFor(() => {
      expect(within(panel).getByLabelText("Имя и фамилия")).toHaveValue("");
    });
    for (const box of within(panel).getAllByRole("checkbox")) expect(box).not.toBeChecked();
  });

  it("смена ширины через 1200 и 390 px не очищает форму приглашения (R3-D-4)", async () => {
    signIn("admin@demo.example");
    renderAt("/admin/org?invite=open&panel=open");
    fireEvent.change(await within(await panelEl()).findByLabelText("Имя и фамилия"), {
      target: { value: "Демо Новый" },
    });
    fireEvent.click(within(await panelEl()).getByRole("checkbox", { name: /^Бухгалтер/ }));

    for (const width of [390, 1440]) {
      act(() => {
        setViewportWidth(width);
      });
      const panel = await panelEl();
      expect(await within(panel).findByLabelText("Имя и фамилия")).toHaveValue("Демо Новый");
      expect(within(panel).getByRole("checkbox", { name: /^Бухгалтер/ })).toBeChecked();
    }
  });

  it("директору ?invite=open ничего не открывает", async () => {
    signIn("director@demo.example");
    renderAt("/admin/org?invite=open&panel=open");

    await screen.findByRole("link", { name: "Открыть карточку: Демо Менеджеров" });
    expect(
      within(await panelEl()).queryByRole("heading", { level: 3, name: "Пригласить сотрудника" }),
    ).toBeNull();
  });
});
