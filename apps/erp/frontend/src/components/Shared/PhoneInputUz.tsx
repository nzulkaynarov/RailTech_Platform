import * as React from 'react';
import { Input } from '@/components/ui/input';

const PREFIX = '+998';

/** National digits from the raw stored value (always "+998…"). */
function nationalFromRaw(raw: string): string {
	const body = raw.startsWith(PREFIX) ? raw.slice(PREFIX.length) : raw;
	return body.replace(/\D/g, '').slice(0, 9);
}

/** National digits from whatever the user typed/pasted into the field. */
function nationalFromInput(input: string): string {
	let digits = input.replace(/\D/g, '');
	if (digits.length > 9 && digits.startsWith('998')) digits = digits.slice(3);
	return digits.slice(0, 9);
}

/** Raw value to store/submit, e.g. "+998901234567". */
function toRawUzPhone(input: string): string {
	return PREFIX + nationalFromInput(input);
}

/** Pretty national display, e.g. "90 123 45 67". */
function formatNational(raw: string): string {
	const d = nationalFromRaw(raw);
	return [d.slice(0, 2), d.slice(2, 5), d.slice(5, 7), d.slice(7, 9)].filter(Boolean).join(' ');
}

interface PhoneInputUzProps {
	value?: string;
	onChange: (raw: string) => void;
	onBlur?: () => void;
	name?: string;
	placeholder?: string;
	disabled?: boolean;
}

/**
 * Uzbekistan phone input. The "+998" country code is a fixed adornment; the user
 * only edits the 9 national digits. Emits the raw value "+998XXXXXXXXX" so the
 * Zod schema can validate against ^\+998\d{9}$.
 */
export const PhoneInputUz: React.FC<PhoneInputUzProps> = ({
	value,
	onChange,
	onBlur,
	name,
	placeholder,
	disabled,
}) => (
	<div className="relative">
		<span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">
			{PREFIX}
		</span>
		<Input
			type="tel"
			inputMode="numeric"
			autoComplete="tel-national"
			name={name}
			disabled={disabled}
			placeholder={placeholder}
			className="pl-14"
			value={formatNational(value ?? '')}
			onChange={(event) => onChange(toRawUzPhone(event.target.value))}
			onBlur={onBlur}
		/>
	</div>
);
