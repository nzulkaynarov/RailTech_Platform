import { useQuery } from '@tanstack/react-query';
import { useEffect } from 'react';

import { getOperator } from '@/api/portal';
import { useTranslation } from 'react-i18next';

import i18n from '@/i18n';

/**
 * Название оператора в текстах кабинета (`{{operator}}`) — из настроек компании (CRM «Настройки · Компания» →
 * ERP → `GET /operator`; задача «Н3a2»), а не из кода. Переменная общая для всех строк (`defaultVariables`), поэтому
 * места вызова `t()` её не передают. Не задано или запрос не удался — пустая строка (`app.operatorFallback`): своего названия компании в кабинете нет, чужое слово («Платформа», «ERP») не подставляем.
 */
export function setOperatorName(name: string | null | undefined): void {
  const operator = name?.trim() || i18n.t('app.operatorFallback');
  const interpolation = i18n.options.interpolation ?? {};
  if (interpolation.defaultVariables?.operator === operator) return;
  i18n.options.interpolation = { ...interpolation, defaultVariables: { ...interpolation.defaultVariables, operator } };
  // react-i18next перерисовывает подписчиков по `languageChanged`: тексты получают новое название без перезагрузки
  i18n.emit('languageChanged', i18n.language);
}

/** Оператор до входа: название, бот, логотип (`GET /operator`) — один запрос на весь кабинет. */
export function useOperator() {
  return useQuery({
    queryKey: ['operator'],
    // название ложится в общие переменные i18n до того, как данные дойдут до компонентов: строки с `{{operator}}`
    // и шапка с `useAppName` обновляются в одном кадре
    queryFn: async () => {
      const operator = await getOperator();
      setOperatorName(operator.name);
      return operator;
    },
    staleTime: 10 * 60_000,
    retry: false,
  });
}

export function useOperatorName(): void {
  const query = useOperator();
  const name = query.data?.name;
  const failed = query.isError;
  useEffect(() => {
    if (name !== undefined || failed) setOperatorName(name ?? null);
  }, [name, failed]);
}

/**
 * «Кабинет <оператор>»: название берётся из данных запроса `operator` и передаётся в `t()` явно, поэтому смена
 * названия перерисовывает шапку и заголовок вкладки без смены языка (`languageChanged` при том же языке не
 * перерисовывает подписчиков react-i18next). Нет названия — нейтральное слово языка из `defaultVariables`.
 */
export function useAppName(): string {
  const { t } = useTranslation();
  const name = useOperator().data?.name?.trim();
  const title = (name ? t('app.name', { operator: name }) : t('app.name')).trim();
  // без названия компании в en остаётся «account» — с заглавной буквы
  return title.charAt(0).toUpperCase() + title.slice(1);
}
