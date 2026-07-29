/**
 * Состояние редактирования строк КП: ошибки ячеек после bulk-сохранения, поля строки добавления
 * и состояние диалога вставки из Excel.
 *
 * Вынесено из QuoteBuilderGrid одним куском, потому что это связка: правка ячейки обязана гасить
 * ошибку именно на этой ячейке (иначе строка остаётся «красной» после исправления), а поля
 * добавления и вставки живут в том же цикле «ввёл → отправил → получил построчные ошибки».
 */

import { useState, useRef } from 'react';
import type { QuoteItem } from '@/api/crmApi';
import type { DraftFieldValue } from '@/components/QuoteBuilder/useQuoteDraft';
import { cellErrorKey } from '@/components/QuoteBuilder/bulkErrors';

interface Args {
	/** Запись поля в черновик (из useQuoteDraft) — редактирование и гашение ошибки атомарны. */
	setField: (id: number, field: keyof QuoteItem, value: DraftFieldValue) => void;
	t: (key: string) => string;
}

export function useGridEditingState({ setField, t }: Args) {
	// Построчные коды отклонения от ПОСЛЕДНЕГО bulk-сохранения (P0-4), ключ `${id}:${field}` → CODE.
	const [cellErrors, setCellErrors] = useState<Record<string, string>>({});
	const [newItemName, setNewItemName] = useState('');
	const [newItemQty, setNewItemQty] = useState<string>('1');
	const [newItemPrice, setNewItemPrice] = useState<string>('0');
	const [showAddRow, setShowAddRow] = useState(false);
	const [pasteOpen, setPasteOpen] = useState(false);
	const [pasteText, setPasteText] = useState('');
	const [pasteRowErrors, setPasteRowErrors] = useState<Record<number, Record<string, string>>>({});
	const addNameRef = useRef<HTMLInputElement>(null);
	const addRowRef = useRef<HTMLTableRowElement>(null);
	const rowRefs = useRef<Map<number, HTMLTableRowElement>>(new Map());

	/** Правка строки И сброс устаревшей ошибки bulk-сохранения ровно на этой ячейке. */
	const handleFieldChange = (id: number, field: keyof QuoteItem, value: DraftFieldValue) => {
		setField(id, field, value);
		const key = cellErrorKey(id, field as string);
		if (cellErrors[key]) {
			setCellErrors((previous) => {
				const next = { ...previous };
				delete next[key];
				return next;
			});
		}
	};

	/** Локализованное сообщение для отклонённой ячейки (undefined — ячейка чистая). */
	const cellError = (id: number, field: string): string | undefined => {
		const code = cellErrors[cellErrorKey(id, field)];
		if (!code) return undefined;
		const key = `quote.validation.${code}`;
		const label = t(key);
		return label === key ? code : label; // нелокализованный новый код → показываем сам код
	};

	return {
		cellErrors, setCellErrors, cellError, handleFieldChange,
		newItemName, setNewItemName, newItemQty, setNewItemQty, newItemPrice, setNewItemPrice,
		showAddRow, setShowAddRow,
		pasteOpen, setPasteOpen, pasteText, setPasteText, pasteRowErrors, setPasteRowErrors,
		addNameRef, addRowRef, rowRefs,
	};
}
