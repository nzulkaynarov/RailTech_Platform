import React from 'react';
import { useTranslation } from 'react-i18next';
import { useDeliveryBases } from '@/hooks/useMasterData';
import { deliveryBasisLabelKey } from '@/lib/codes';
import {
	Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';

interface DeliveryBasisSelectProps {
	value?: number | null;
	onChange: (id: number) => void;
	disabled?: boolean;
}

/**
 * Incoterm picker for the КП header. Selecting a basis drives which cost rows the
 * builder shows (the grid reads the responsibility flags off the quote's
 * delivery_basis_data after this PATCH lands).
 */
export const DeliveryBasisSelect: React.FC<DeliveryBasisSelectProps> = ({ value, onChange, disabled }) => {
	const { t } = useTranslation();
	const { data: bases = [] } = useDeliveryBases();

	return (
		<Select
			value={value ? String(value) : undefined}
			onValueChange={(v) => onChange(Number(v))}
			disabled={disabled}
		>
			<SelectTrigger className="h-8 w-full max-w-[240px]" aria-label={t('quote.deliveryBasis')}>
				<SelectValue placeholder={t('quote.deliveryBasisPlaceholder')} />
			</SelectTrigger>
			<SelectContent>
				{bases.map((basis) => (
					<SelectItem key={basis.id} value={String(basis.id)}>
						{basis.code} — {deliveryBasisLabelKey(basis.code) ? t(deliveryBasisLabelKey(basis.code)) : basis.name}
					</SelectItem>
				))}
			</SelectContent>
		</Select>
	);
};
