import { describe, it, expect } from 'vitest';
import { NAVIGABLE_PAGES, PAGE_IDS } from '../config/pageRegistry';

// Реестр страниц заменил ЧЕТЫРЕ параллельных списка идентификаторов, которые раньше жили в
// App.tsx (union-тип Page, наборы гейтов, validTypes в handleNavigate, switch рендера). Тест
// держит выведенные из реестра наборы против явных литералов — если правка реестра сдвинет
// маршрут, тест упадёт здесь, а не багом на проде.
//
// Осознанные изменения против исходного снимка B2B:
//   • M1-ERP-02 (волна 1a): операторская плоскость удалена — страницы `admin-*` и флаги
//     `admin` / `adminReachable` ушли из реестра вместе с `PlatformAdminShell`.
//   • M1-ERP-02 (волна 1c): порог проверки компании удалён.
//   • M1-ERP-02 (волна 3): ERP — бэк-офис одной компании. Флаги стороны `client` / `seller` и наборы
//     BUYER_PAGES / SELLER_PAGES удалены; покупательские страницы `my-requests` («Мои заявки») и
//     `suppliers` («Поставщики») ушли в Cabinet. `products` (бывшая витрина каталога покупателя)
//     остался рабочим алиасом «Моих товаров» — хэш напечатан в закладках и туре.

const asSorted = (value: Iterable<string>) => [...value].sort();

describe('реестр страниц', () => {
  it('PAGE_IDS — все маршруты бэк-офиса', () => {
    expect(asSorted(PAGE_IDS)).toEqual(
      asSorted([
        'dashboard', 'profile', 'settings', 'help',
        'products', 'nomenclature', 'my-products', 'product-new', 'product-edit',
        'catalog-reference', 'hs-directory', 'categories', 'catalog-import',
        'product_detail',
        'contracts', 'invoices', 'payments', 'fulfillments', 'acts', 'other-documents', 'company-files',
        'sourcing-requests', 'crm-deals', 'crm-quotes', 'request-detail', 'deal-quote', 'clients',
      ]),
    );
  });

  it('NAVIGABLE_PAGES — цели, которые принимает handleNavigate', () => {
    expect(asSorted(NAVIGABLE_PAGES)).toEqual(
      asSorted([
        'dashboard', 'profile', 'settings', 'help',
        'products', 'nomenclature', 'my-products', 'product-new',
        'catalog-reference', 'hs-directory', 'categories', 'catalog-import',
        'contracts', 'invoices', 'payments', 'fulfillments', 'acts', 'other-documents', 'company-files',
        'sourcing-requests', 'crm-deals', 'crm-quotes', 'clients',
      ]),
    );
  });

  it('покупательских страниц в реестре нет (M1-ERP-02 волна 3)', () => {
    for (const clientPage of ['my-requests', 'suppliers']) {
      expect(PAGE_IDS).not.toContain(clientPage);
    }
  });

  it('идентификаторы уникальны', () => {
    expect(PAGE_IDS.length).toBe(new Set(PAGE_IDS).size);
  });

  it('навигация из меню не предлагает параметризованные маршруты', () => {
    // `handleNavigate` принимает голый идентификатор, поэтому маршрут, требующий id
    // в хэше, нельзя открыть кликом по пункту меню — только адресным переходом.
    for (const id of ['product_detail', 'product-edit', 'request-detail', 'deal-quote']) {
      expect(NAVIGABLE_PAGES.has(id)).toBe(false);
    }
  });
});
