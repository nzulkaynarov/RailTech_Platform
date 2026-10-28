import { useMemo } from "react";

import type { CompanyArticle } from "../../shared/api/generated/model";
import { useListCompanyArticles } from "../../shared/api/generated/platform-bff";
import { HELP_ARTICLES, type HelpArticle } from "./articles";

/** Адрес статьи компании в Помощи — `/help/articles/company-<id>`; у продуктовых статей слаг без этого префикса. */
export const COMPANY_PREFIX = "company-";

export const companySlug = (id: number) => `${COMPANY_PREFIX}${String(id)}`;
/** Слаг статьи компании — `company-<число>`; продуктовая статья `company-articles` (справка к экрану) под него не подходит. */
export const isCompanySlug = (slug: string) => /^company-\d+$/.test(slug);

/** Статья компании в виде статьи помощи: порядок — как отдал сервер (новые выше), разделов каталога у неё нет. */
export function toHelpArticle(article: CompanyArticle, index: number): HelpArticle {
  return {
    slug: companySlug(article.id),
    title: article.title,
    sections: [],
    order: index,
    body: article.body,
    source: "company",
    language: article.language,
    updatedAt: article.updated_at,
  };
}

export interface HelpArticles {
  /** Продуктовые статьи (`docs/kb/help`) */
  product: readonly HelpArticle[];
  /** Опубликованные статьи компании (из CRM) */
  company: readonly HelpArticle[];
  /** Все вместе: продуктовые, затем компании — для общего поиска и поиска статьи по адресу */
  all: readonly HelpArticle[];
  /** Статьи компании ещё грузятся */
  pending: boolean;
  /** Статьи компании не загрузились: продуктовые доступны, раздел «Как у нас принято» — с пометкой */
  failed: boolean;
}

/**
 * Статьи помощи: продуктовые из сборки и статьи компании из CRM (`GET /help/company-articles`, только опубликованные).
 * Сбой загрузки статей компании не ломает Помощь: продуктовые статьи открываются как обычно.
 */
export function useHelpArticles(): HelpArticles {
  const query = useListCompanyArticles({ query: { staleTime: 30_000 } });
  const items = query.data?.items;
  const company = useMemo(() => (items ?? []).map(toHelpArticle), [items]);
  return useMemo(
    () => ({
      product: HELP_ARTICLES,
      company,
      all: [...HELP_ARTICLES, ...company],
      pending: query.isPending,
      failed: query.isError,
    }),
    [company, query.isPending, query.isError],
  );
}
