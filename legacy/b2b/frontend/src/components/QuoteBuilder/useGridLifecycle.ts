/**
 * Побочные эффекты жизненного цикла конструктора КП: выход из фокус-режима по Esc и две
 * страховки от потери несохранённых правок (в приложении и на уровне вкладки браузера).
 *
 * Вынесено из QuoteBuilderGrid — три `useEffect` подряд, не связанные с рендером таблицы.
 */

import { useEffect } from 'react';

interface Args {
	fullscreen: boolean;
	setFullscreen: (value: boolean) => void;
	hasUnsavedChanges: boolean;
	/** Поднимаем наверх, чтобы страница-хозяин (DealQuotePage) охраняла внутреннюю навигацию. */
	onDirtyChange?: (hasUnsavedChanges: boolean) => void;
}

export function useGridLifecycle({ fullscreen, setFullscreen, hasUnsavedChanges, onDirtyChange }: Args) {
	// Esc выходит из фокус-режима (зеркалит переключатель ⛶) — у наложенного диалога свой Escape.
	useEffect(() => {
		if (!fullscreen) return;
		const onKey = (event: KeyboardEvent) => {
			if (event.key !== 'Escape') return;
			if (event.defaultPrevented || document.querySelector('[role="dialog"], [role="alertdialog"]')) return;
			setFullscreen(false);
		};
		window.addEventListener('keydown', onKey);
		return () => window.removeEventListener('keydown', onKey);
	}, [fullscreen, setFullscreen]);

	// Сигнал о несохранённых правках наверх — страница охраняет внутреннюю навигацию (кнопка «Назад»).
	useEffect(() => {
		onDirtyChange?.(hasUnsavedChanges);
	}, [hasUnsavedChanges, onDirtyChange]);

	// Страховка уровня браузера: предупредить перед закрытием вкладки / перезагрузкой.
	useEffect(() => {
		if (!hasUnsavedChanges) return;
		const handleBeforeUnload = (event: BeforeUnloadEvent) => {
			event.preventDefault();
			event.returnValue = '';
		};
		window.addEventListener('beforeunload', handleBeforeUnload);
		return () => window.removeEventListener('beforeunload', handleBeforeUnload);
	}, [hasUnsavedChanges]);
}
