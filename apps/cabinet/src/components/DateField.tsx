import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Input } from '@/components/ui/input';
import { isoToText, maskDate, textToIso } from '@/lib/dateInput';

/**
 * Поле даты кабинета вместо системного `input type="date"` (он показывал `10/14/2026` на языке браузера, B-CABFIX-1;
 * образец — Платформа `shared/ui/DateField`, UX-2a). Своего календаря в кабинете нет, поэтому — поле с маской
 * `ДД.ММ.ГГГГ` (цифры, точки ставятся сами), подсказка формата на языке интерфейса. Наружу — ключ `YYYY-MM-DD`, `''` для
 * пустого поля и `null`, пока дата набрана не полностью или не существует: форма пишет ошибку словами. Границы (не позже
 * сегодня и т. п.) проверяет форма — как с системным полем.
 */
export function DateField({
  id,
  value,
  onChange,
  invalid,
  describedBy,
  className,
}: {
  id: string;
  /** Ключ `YYYY-MM-DD`, `''` или `null` (набрано не до конца). */
  value: string | null;
  onChange: (value: string | null) => void;
  invalid?: boolean;
  describedBy?: string;
  className?: string;
}) {
  const { t } = useTranslation();
  const [text, setText] = useState(() => isoToText(value));
  const [shown, setShown] = useState(value);
  // Значение сменили снаружи (сброс формы) — показать его; `null` — наш же неполный ввод, текст не трогаем.
  if (value !== shown) {
    setShown(value);
    if (value !== null && value !== textToIso(text)) setText(isoToText(value));
  }
  return (
    <Input
      id={id}
      className={className}
      inputMode="numeric"
      autoComplete="off"
      maxLength={10}
      placeholder={t('common.date.placeholder')}
      value={text}
      aria-describedby={describedBy}
      aria-invalid={invalid || undefined}
      onChange={(event) => {
        const next = maskDate(event.target.value);
        setText(next);
        onChange(textToIso(next));
      }}
    />
  );
}
