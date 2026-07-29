/**
 * UI-состояние конструктора КП: открытые диалоги, режимы отображения и «занятости».
 *
 * Вынесено из QuoteBuilderGrid: тринадцать разрозненных `useState` подряд читались как шум и при
 * каждой правке заставляли глазами искать, где кончается состояние и начинается логика.
 *
 * ВАЖНО: здесь ТОЛЬКО UI. Ничего из этого не попадает в `draftItems`, поэтому раскрытие строки,
 * открытие диалога или полноэкранный режим никогда не поднимают флаг несохранённых изменений.
 */

import { useState } from 'react';

export function useGridDialogState() {
	const [showAiMatch, setShowAiMatch] = useState(false);
	const [importOpen, setImportOpen] = useState(false); // Q2: импорт позиций из файла
	const [showGenerateQuote, setShowGenerateQuote] = useState(false);
	const [showSettings, setShowSettings] = useState(false);
	const [pricingBusy, setPricingBusy] = useState(false);
	const [draftBusy, setDraftBusy] = useState(false);

	const [expandedRowId, setExpandedRowId] = useState<number | null>(null);
	const [activeTab, setActiveTab] = useState<'items' | 'charges'>('items');
	const [fullscreen, setFullscreen] = useState(false);
	const [deleteTarget, setDeleteTarget] = useState<number | null>(null);
	// Ручная привязка/пере-привязка товара к строке КП (человеческий аналог AI-подбора).
	const [reassignItemId, setReassignItemId] = useState<number | null>(null);

	// Диалог конфликта оптимистической блокировки (волна 3): сохранение, проигравшее гонку коллеге,
	// открывает его вместо записи. `conflictIds` — устаревшие строки; диалог открывает ТОЛЬКО
	// версионированное bulk-сохранение и всегда с непустым набором (pricing-assist версии не несёт,
	// поэтому 409 дать не может). Случая «пустой список = сбросить всё» не существует.
	const [conflictOpen, setConflictOpen] = useState(false);
	const [conflictIds, setConflictIds] = useState<number[]>([]);

	const toggleRow = (id: number) => setExpandedRowId((current) => (current === id ? null : id));

	return {
		showAiMatch, setShowAiMatch,
		importOpen, setImportOpen,
		showGenerateQuote, setShowGenerateQuote,
		showSettings, setShowSettings,
		pricingBusy, setPricingBusy,
		draftBusy, setDraftBusy,
		expandedRowId, setExpandedRowId, toggleRow,
		activeTab, setActiveTab,
		fullscreen, setFullscreen,
		deleteTarget, setDeleteTarget,
		reassignItemId, setReassignItemId,
		conflictOpen, setConflictOpen, conflictIds, setConflictIds,
	};
}
