import { HttpResponse, http } from "msw";

import type { Dictionary, DictionaryItem } from "../shared/api/generated/model";
import { readSession } from "./mockSession";

const names = (ru: string, uz: string, en: string) => ({ ru, uz, en });

/**
 * Категории и производители каталога общим ресурсом справочников (план 3.8) на моках: код строки выдаёт ERP,
 * у категории — родитель (код), учёт единиц и документ соответствия, у производителя — страна (код) и сайт.
 */
export const CATALOG_FILE_DICTIONARIES: Dictionary[] = [
  {
    kind: "categories",
    owner: "erp",
    area: "calc",
    codes: "generated",
    closed: false,
    name: names("Категории товаров", "Mahsulot toifalari", "Product categories"),
    attrs: [
      {
        key: "parent",
        type: "text",
        name: names("Родитель (код)", "Ota toifa (kodi)", "Parent (code)"),
        required: false,
      },
      {
        key: "tracking",
        type: "choice",
        name: names("Учёт единиц", "Birliklar hisobi", "Unit tracking"),
        required: false,
        options: [
          { value: "serial", name: names("Серийный", "Seriyali", "Serial") },
          { value: "lot", name: names("Партия", "Partiya", "Lot") },
          { value: "none", name: names("Только количество", "Faqat miqdor", "Quantity only") },
        ],
      },
      {
        key: "requires_conformity_doc",
        type: "boolean",
        name: names(
          "Нужен документ соответствия",
          "Muvofiqlik hujjati kerak",
          "Conformity document required",
        ),
        required: false,
      },
    ],
  },
  {
    kind: "manufacturers",
    owner: "erp",
    area: "calc",
    codes: "generated",
    closed: false,
    name: names("Бренды", "Brendlar", "Brands"),
    attrs: [
      {
        key: "country",
        type: "text",
        name: names("Страна (код)", "Mamlakat (kodi)", "Country (code)"),
        required: false,
      },
      { key: "website", type: "text", name: names("Сайт", "Sayt", "Website"), required: false },
    ],
  },
];

const ROWS: Record<string, DictionaryItem[]> = {
  categories: [
    {
      code: "1",
      name: names("Запчасти", "Ehtiyot qismlar", "Spare parts"),
      attrs: { parent: "", tracking: "none", requires_conformity_doc: false },
      active: true,
      position: 10,
    },
    {
      code: "2",
      name: names("Подшипники", "Podşipniklar", "Bearings"),
      attrs: { parent: "1", tracking: "lot", requires_conformity_doc: true },
      active: true,
      position: 20,
    },
  ],
  manufacturers: [
    {
      code: "1",
      name: names("Демо-Завод", "Demo-Zavod", "Demo Plant"),
      attrs: { country: "UZ", website: "https://demo-plant.example" },
      active: true,
      position: 10,
    },
    {
      code: "2",
      name: names("Вымышленный Подшипник", "", "Fictional Bearing"),
      attrs: { country: "DE", website: "" },
      active: true,
      position: 20,
    },
  ],
};

const expired = () =>
  HttpResponse.json(
    { code: "SESSION_EXPIRED", message: "Сессия истекла", source: "bff" },
    { status: 401 },
  );

export const catalogFilesHandlers = (["categories", "manufacturers"] as const).flatMap((kind) => [
  http.get(`*/dictionaries/${kind}/export`, () => {
    if (!readSession()) return expired();
    const attrs = CATALOG_FILE_DICTIONARIES.find((d) => d.kind === kind)?.attrs ?? [];
    const header = ["code", "name_ru", "name_uz", "name_en", "active", ...attrs.map((a) => a.key)];
    const lines = (ROWS[kind] ?? []).map((item) =>
      [
        item.code,
        item.name.ru,
        item.name.uz,
        item.name.en,
        item.active ? "да" : "нет",
        ...attrs.map((a) => String(item.attrs[a.key] ?? "")),
      ].join(";"),
    );
    return new HttpResponse([header.join(";"), ...lines].join("\n"), {
      headers: {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": `attachment; filename="${kind}.csv"`,
      },
    });
  }),
  http.get(`*/dictionaries/${kind}`, () => {
    if (!readSession()) return expired();
    return HttpResponse.json({ items: ROWS[kind] ?? [] });
  }),
]);
