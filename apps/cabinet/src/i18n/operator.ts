import { useQuery } from '@tanstack/react-query';
import { useEffect } from 'react';

import { getOperator } from '@/api/portal';
import i18n from '@/i18n';

/**
 * Название оператора в текстах кабинета (`{{operator}}`) — из настроек компании (CRM «Настройки · Компания» →
 * ERP → `GET /operator`; задача «Н3a2»), а не из кода. Переменная общая для всех строк (`defaultVariables`), поэтому
 * места вызова `t()` её не передают. Не задано или запрос не удался — нейтральное слово языка (`app.operatorFallback`).
 */
export function setOperatorName(name: string | null | undefined): void {
  const operator = name?.trim() || i18n.t('app.operatorFallback');
  const interpolation = i18n.options.interpolation ?? {};
  if (interpolation.defaultVariables?.operator === operator) return;
  i18n.options.interpolation = { ...interpolation, defaultVariables: { ...interpolation.defaultVariables, operator } };
  // react-i18next перерисовывает подписчиков по `languageChanged`: тексты получают новое название без перезагрузки
  i18n.emit('languageChanged', i18n.language);
}

export function useOperatorName(): void {
  const query = useQuery({ queryKey: ['operator'], queryFn: getOperator, staleTime: 10 * 60_000, retry: false });
  const name = query.data?.name;
  const failed = query.isError;
  useEffect(() => {
    if (name !== undefined || failed) setOperatorName(name ?? null);
  }, [name, failed]);
}
