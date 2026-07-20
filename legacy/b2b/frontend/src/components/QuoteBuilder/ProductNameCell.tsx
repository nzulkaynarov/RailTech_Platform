import React, { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { AlertTriangle, Link2, Loader2 } from 'lucide-react';
import type { QuoteItem } from '@/api/crmApi';
import type { Product } from '@/api/catalogApi';
import { translateApiError } from '@/lib/apiError';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Popover, PopoverAnchor, PopoverContent } from '@/components/ui/popover';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useProductSearch } from '@/hooks/useCatalog';
import { useDebouncedValue } from '@/hooks/useDebouncedValue';
import { useReassignProduct } from '@/hooks/useCRM';

const MIN_QUERY_LENGTH = 2;

interface ProductNameCellProps {
	item: QuoteItem;
	/** 1-based visible order — renders the «N.» prefix. */
	index: number;
	/** Opens ReassignProductDialog (AI candidates / clear) for the unbound-line fallback. */
	onBrowseCandidates: (itemId: number) => void;
}

/** Один различающий подзаголовок кандидата: артикул · ГОСТ · MPN (пустые опускаются). */
function candidateSubtitle(product: Product): string {
	return [product.sku, product.gost_drawing, product.manufacturer_part_number]
		.map((part) => (part || '').trim())
		.filter(Boolean)
		.join(' · ');
}

/**
 * Наименование позиции КП как typeahead-комбобокс (spec §5 п.13).
 *
 * Печать ≥2 символов → дебаунс-поиск каталога (`useProductSearch`, тот же
 * `catalog/products/?search=` эндпоинт) → выпадающий список; выбор привязывает товар
 * через СУЩЕСТВУЮЩУЮ мутацию `useReassignProduct` (эндпоинт reassign-product, тот же, что
 * у ReassignProductDialog). Свободный ввод без выбора НЕ сохраняется как новое имя —
 * imported_raw_name не редактируется inline в текущей модели, поэтому на blur поле
 * возвращается к каноническому имени (create-on-the-fly = позиция просто остаётся вне
 * каталога с прежним именем). Save-семантика сохранена.
 *
 * Клавиатура: пока список ЗАКРЫТ, стрелки/Enter всплывают в делегированный
 * useGridKeyboard (инпут несёт data-cell-col="name") — навигация по колонке имени
 * работает. Когда список ОТКРЫТ, стрелки/Enter/Escape перехватываются здесь
 * (preventDefault + stopPropagation), поэтому grid-навигация их не видит.
 */
export function ProductNameCell({ item, index, onBrowseCandidates }: ProductNameCellProps) {
	const { t } = useTranslation();
	const reassign = useReassignProduct();
	const displayName = item.product_name || item.imported_raw_name || '';

	const [editing, setEditing] = useState(false);
	const [draft, setDraft] = useState('');
	const [open, setOpen] = useState(false);
	const [highlight, setHighlight] = useState(0);
	const listboxId = useId();

	const debounced = useDebouncedValue(draft, 250);
	const { data: rawResults = [], isFetching } = useProductSearch(open ? debounced : '');
	const results = open ? rawResults : [];
	const activeIndex = results.length ? Math.min(highlight, results.length - 1) : 0;

	const inputValue = editing ? draft : displayName;
	const isBound = !!item.product;

	const closeDropdown = () => {
		setOpen(false);
		setHighlight(0);
	};

	const commitSelection = (product: Product) => {
		closeDropdown();
		setEditing(false);
		setDraft('');
		reassign
			.mutateAsync({ quoteItemId: item.id, productId: product.id })
			.then(() => toast.success(t('rematchDialog.assigned')))
			.catch((error) => toast.error(translateApiError(error)));
	};

	const handleChange = (next: string) => {
		setEditing(true);
		setDraft(next);
		setHighlight(0);
		setOpen(next.trim().length >= MIN_QUERY_LENGTH);
	};

	const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
		// Список ЗАКРЫТ → не трогаем стрелки/Enter: пусть всплывают в grid-навигацию.
		// Единственное исключение — Escape при открытом (обрабатывается ниже).
		if (!open || results.length === 0) {
			if (event.key === 'Escape' && open) {
				event.preventDefault();
				event.stopPropagation();
				closeDropdown();
			}
			return;
		}
		switch (event.key) {
			case 'ArrowDown':
				event.preventDefault();
				event.stopPropagation();
				setHighlight((current) => Math.min(current + 1, results.length - 1));
				break;
			case 'ArrowUp':
				event.preventDefault();
				event.stopPropagation();
				setHighlight((current) => Math.max(current - 1, 0));
				break;
			case 'Enter': {
				event.preventDefault();
				event.stopPropagation();
				const picked = results[activeIndex];
				if (picked) commitSelection(picked);
				break;
			}
			case 'Escape':
				event.preventDefault();
				event.stopPropagation();
				closeDropdown();
				break;
			default:
				break;
		}
	};

	const handleBlur = () => {
		setEditing(false);
		setDraft('');
		closeDropdown();
	};

	return (
		// B2: `w-full min-w-0` propagates the elastic name column's width down the flex chain. Without
		// `min-w-0` a flex item's `min-width:auto` refuses to shrink below its content, which is what
		// pinned the input at its intrinsic width and truncated the name while space sat unused.
		<div className="flex w-full min-w-0 flex-col leading-tight pr-4">
			<Popover open={open} onOpenChange={(next) => { if (!next) closeDropdown(); }}>
				<PopoverAnchor asChild>
					<div className="flex w-full min-w-0 items-center gap-2">
						{!isBound ? (
							<AlertTriangle className="size-3 shrink-0 text-warning" aria-label={t('sourcing.noMatch')} />
						) : (
							<Tooltip>
								<TooltipTrigger asChild>
									<Link2 className="size-3 shrink-0 text-primary" aria-label={t('quote.typeahead.linked')} />
								</TooltipTrigger>
								<TooltipContent>{t('quote.typeahead.linked')}</TooltipContent>
							</Tooltip>
						)}
						<span className="text-xs font-mono text-muted-foreground tabular-nums">{index}.</span>
						<Input
							type="text"
							role="combobox"
							aria-expanded={open}
							aria-controls={listboxId}
							aria-autocomplete="list"
							aria-activedescendant={open && results.length ? `${listboxId}-opt-${activeIndex}` : undefined}
							aria-label={t('quote.typeahead.ariaLabel')}
							placeholder={t('quote.typeahead.placeholder')}
							data-cell-row={item.id}
							data-cell-col="name"
							className="h-7 min-w-0 flex-1 truncate border-none bg-transparent px-1 text-sm font-semibold shadow-none focus-visible:ring-1 focus-visible:ring-ring focus-visible:ring-inset"
							title={displayName || undefined}
							value={inputValue}
							onFocus={() => { setEditing(true); setDraft(displayName); }}
							onChange={(event) => handleChange(event.target.value)}
							onKeyDown={handleKeyDown}
							onBlur={handleBlur}
						/>
						{item.product_domain && (
							<Badge variant="outline" className="text-xs px-1.5 py-0 shrink-0">{item.product_domain}</Badge>
						)}
					</div>
				</PopoverAnchor>
				<PopoverContent
					align="start"
					sideOffset={2}
					className="w-80 p-0"
					// Focus stays in the input so the seller keeps typing; the list is a passive
					// listbox driven by aria-activedescendant, never focused.
					onOpenAutoFocus={(event) => event.preventDefault()}
				>
					<ul id={listboxId} role="listbox" aria-label={t('quote.typeahead.listLabel')} className="max-h-64 overflow-auto py-1">
						{isFetching && results.length === 0 ? (
							<li className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground">
								<Loader2 className="size-3 animate-spin" />
								{t('quote.typeahead.searching')}
							</li>
						) : results.length === 0 ? (
							<li className="px-3 py-2 text-xs text-muted-foreground">{t('quote.typeahead.noResults')}</li>
						) : (
							results.map((product, optionIndex) => {
								const subtitle = candidateSubtitle(product);
								return (
									<li
										key={product.id}
										id={`${listboxId}-opt-${optionIndex}`}
										role="option"
										aria-selected={optionIndex === activeIndex}
										// preventDefault keeps focus in the input, so onBlur does not fire
										// and swallow the click before the selection lands.
										onMouseDown={(event) => event.preventDefault()}
										onMouseEnter={() => setHighlight(optionIndex)}
										onClick={() => commitSelection(product)}
										className={cn(
											'flex cursor-pointer flex-col gap-0.5 px-3 py-2',
											optionIndex === activeIndex ? 'bg-accent text-accent-foreground' : 'hover:bg-muted/60',
										)}
									>
										<span className="truncate text-sm font-medium">{product.name}</span>
										{subtitle && <span className="truncate font-mono text-xs text-muted-foreground">{subtitle}</span>}
									</li>
								);
							})
						)}
					</ul>
				</PopoverContent>
			</Popover>

			{isBound ? (
				<span className="mt-0.5 truncate text-xs text-muted-foreground">
					{item.offer_supplier_name || item.product_sku || '—'}
				</span>
			) : (
				<button
					type="button"
					onClick={() => onBrowseCandidates(item.id)}
					className="mt-0.5 flex items-center gap-1 text-xs font-medium text-primary hover:underline"
				>
					<Link2 className="size-3 shrink-0" />
					{t('quote.attachProduct')}
				</button>
			)}
		</div>
	);
}
