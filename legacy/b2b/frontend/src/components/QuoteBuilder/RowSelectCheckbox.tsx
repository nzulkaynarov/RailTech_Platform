import React, { useCallback, useRef } from 'react';
import { Checkbox } from '@/components/ui/checkbox';

interface RowSelectCheckboxProps {
	checked: boolean;
	/** Accessible name — «Выбрать строку N» (the caller localizes it). */
	ariaLabel: string;
	/** Toggle this row; `shiftKey` selects the range from the last-clicked row (useRowSelection). */
	onToggle: (shiftKey: boolean) => void;
}

/**
 * Row-selection checkbox for the КП grid (DT7).
 *
 * Radix' `onCheckedChange` hands over the NEXT checked state but no DOM event, so the Shift
 * modifier for a range-select has to be captured on the interaction that produced the change —
 * `pointerdown` for a mouse click, `keydown` for Space/Enter. Both write a ref that
 * `onCheckedChange` reads and immediately resets, which keeps the semantic
 * `onCheckedChange` contract (a11y: keyboard toggling works, no `onClick` + event cast) while
 * preserving Shift+click range selection.
 */
export const RowSelectCheckbox: React.FC<RowSelectCheckboxProps> = ({ checked, ariaLabel, onToggle }) => {
	const shiftHeldRef = useRef(false);

	const rememberShift = useCallback((event: React.PointerEvent | React.KeyboardEvent) => {
		shiftHeldRef.current = event.shiftKey;
	}, []);

	const handleCheckedChange = useCallback(() => {
		const shiftKey = shiftHeldRef.current;
		shiftHeldRef.current = false;
		onToggle(shiftKey);
	}, [onToggle]);

	return (
		<Checkbox
			checked={checked}
			onPointerDown={rememberShift}
			onKeyDown={rememberShift}
			onCheckedChange={handleCheckedChange}
			aria-label={ariaLabel}
		/>
	);
};
