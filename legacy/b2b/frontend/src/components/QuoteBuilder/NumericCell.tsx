import React, { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';

interface NumericCellProps {
	/** The committed (server/draft) value shown when the cell is NOT focused. */
	value: string | number | null | undefined;
	/** Called with the normalized, clamped string ONLY on a valid commit (blur/Enter). */
	onCommit: (value: string) => void;
	/** Clamp floor (inclusive). Sub-min entries clamp silently to `min`. */
	min?: number;
	/** Clamp ceiling (inclusive). Over-max entries clamp and toast `maxToastKey`. */
	max?: number;
	/** i18n key for the "value too large" warning toast (interpolates `{ max }`). */
	maxToastKey?: string;
	/** Max fractional digits for out-of-focus grouped display (0 → integer field). */
	maxFractionDigits?: number;
	ariaLabel?: string;
	className?: string;
	disabled?: boolean;
	/** Mark the cell as rejected by the last bulk save → aria-invalid + destructive ring. */
	invalid?: boolean;
	/** Localized message for the rejection (shown as the native cell tooltip). */
	errorMessage?: string;
	/** Row id — registers the cell for grid keyboard navigation (useGridKeyboard, WP-G). */
	dataCellRow?: number;
	/** Column key (e.g. «quantity») — pairs with dataCellRow for arrow/Enter cell navigation. */
	dataCellCol?: string;
	/**
	 * DT1 — makes the cell NULLABLE: "empty" becomes a real, distinct value instead of a no-op.
	 *
	 * Opt-in. When provided: a `null`/`''` value renders as a genuinely EMPTY field (so
	 * `placeholder` shows through instead of a fabricated «0»), and committing an empty buffer calls
	 * `onClear()` INSTEAD of the default revert. Every other numeric cell in the grid keeps the
	 * original behaviour — empty reverts and «0» is never committed by accident.
	 *
	 * This is the mechanism behind «пустая ячейка наценки = наследовать маржу КП»: clearing must
	 * write `null`, and `null` is NOT `0` (which would mean «продать по себестоимости»).
	 */
	onClear?: () => void;
	/** Shown when the field is empty — used to render the INHERITED value as muted ghost text. */
	placeholder?: string;
}

/**
 * Strip grouping/whitespace and normalize the decimal comma → dot. The `\s` class
 * covers the regular space plus the no-break (U+00A0) / narrow no-break (U+202F)
 * spaces that Intl grouping emits, so pasted grouped numbers parse cleanly.
 */
const normalizeNumeric = (raw: string): string =>
	raw.replace(/,/g, '.').replace(/\s/g, '');

/**
 * Safe numeric input for the КП grid (WP-D / spec §2 P0-5).
 *
 * Fixes the raw `<input type="number">` failure modes: you can clear and retype
 * without the field snapping to «0»; «1234,50» (decimal comma) parses instead of
 * collapsing to empty; the mouse wheel can't nudge a focused value; and out of
 * focus the number is grouped by locale so 9-digit UZS stays readable. Empty is
 * allowed WHILE editing; commit happens on blur/Enter; an invalid entry reverts.
 */
export const NumericCell: React.FC<NumericCellProps> = ({
	value,
	onCommit,
	min,
	max,
	maxToastKey,
	maxFractionDigits = 2,
	ariaLabel,
	className,
	disabled,
	invalid,
	errorMessage,
	dataCellRow,
	dataCellCol,
	onClear,
	placeholder,
}) => {
	const { t, i18n } = useTranslation();
	// Non-null only WHILE the cell is focused (holds the raw, ungrouped edit buffer).
	const [editBuffer, setEditBuffer] = useState<string | null>(null);
	// Set by Escape so the imminent blur reverts instead of committing.
	const skipCommitRef = useRef(false);

	const isEditing = editBuffer !== null;

	// DT1: a nullable cell with no value renders EMPTY, not «0» — the two mean different things and
	// the placeholder (the inherited value) has to be visible through it.
	const isNullable = onClear !== undefined;
	const isEmptyValue = value === null || value === undefined || value === '';
	const groupedDisplay = isNullable && isEmptyValue
		? ''
		: new Intl.NumberFormat(i18n.language, {
			maximumFractionDigits: maxFractionDigits,
		}).format(Number(value ?? 0));

	const displayValue = isEditing ? editBuffer : groupedDisplay;

	const commit = () => {
		const normalized = normalizeNumeric(editBuffer ?? '');
		// DT1: on a NULLABLE cell an emptied field is a deliberate «сбросить в наследование» —
		// report it as a clear (the caller writes null) rather than silently reverting. Checked
		// BEFORE the revert branch below, and only for a truly empty buffer: unparseable junk still
		// reverts, so a fat-fingered «12x» can never be read as "clear the override".
		//
		// `!isEmptyValue` makes the clear a NO-OP when the cell was already empty. Without it,
		// merely tabbing THROUGH an inheriting margin cell would write null-over-null, marking the
		// row dirty and shipping it in the next Save payload — a phantom edit on a line the seller
		// never touched (and, with optimistic locking, a pointless 409 surface).
		if (isNullable && normalized === '') {
			if (!isEmptyValue) onClear();
			setEditBuffer(null);
			return;
		}
		// Empty or unparseable → revert to the last committed value (never commit «0»).
		if (normalized === '' || Number.isNaN(Number(normalized))) {
			setEditBuffer(null);
			return;
		}
		let parsed = Number(normalized);
		if (min != null && parsed < min) parsed = min;
		if (max != null && parsed > max) {
			parsed = max;
			if (maxToastKey) toast.warning(t(maxToastKey, { max }));
		}
		onCommit(String(parsed));
		setEditBuffer(null);
	};

	return (
		<Input
			type="text"
			inputMode="decimal"
			aria-label={ariaLabel}
			placeholder={placeholder}
			aria-invalid={invalid || undefined}
			data-cell-row={dataCellRow}
			data-cell-col={dataCellCol}
			title={invalid ? errorMessage : undefined}
			disabled={disabled}
			className={cn(className, invalid && 'border-destructive ring-1 ring-destructive')}
			value={displayValue}
			onFocus={() => setEditBuffer(value == null ? '' : String(value))}
			onChange={(event) => setEditBuffer(event.target.value)}
			onBlur={() => {
				if (skipCommitRef.current) {
					skipCommitRef.current = false;
					setEditBuffer(null);
					return;
				}
				commit();
			}}
			onKeyDown={(event) => {
				if (event.key === 'Enter') {
					event.preventDefault();
					event.currentTarget.blur(); // → onBlur commits
				} else if (event.key === 'Escape') {
					event.preventDefault();
					skipCommitRef.current = true;
					const input = event.currentTarget;
					input.blur(); // → onBlur reverts (skipCommitRef path)
					// Excel-style: Escape cancels the edit but the cell KEEPS focus (grid
					// navigation must not dump the seller back to <body>). Refocus re-enters
					// edit mode on the reverted server value.
					input.focus();
				}
			}}
			// Guard against the mouse wheel silently changing a focused value.
			onWheel={(event) => event.currentTarget.blur()}
		/>
	);
};
