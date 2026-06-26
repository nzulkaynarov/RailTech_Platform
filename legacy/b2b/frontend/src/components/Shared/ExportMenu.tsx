import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Download, FileText, FileSpreadsheet, FileType, Loader2 } from 'lucide-react';
import { crmApi } from '@/api/crmApi';
import { Button } from '@/components/ui/button';
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

type ExportFormat = 'pdf' | 'xlsx' | 'csv';

interface ExportMenuProps {
	quoteId: number;
	disabled?: boolean;
}

/**
 * On-demand multi-format КП export dropdown ("Экспорт" → PDF / Excel / CSV).
 * Each item streams the file from GET crm/quotes/<id>/export/?format=<fmt> and
 * triggers a browser download. Seller cost/margin columns are gated server-side.
 */
export const ExportMenu: React.FC<ExportMenuProps> = ({ quoteId, disabled }) => {
	const { t } = useTranslation();
	const [exportingFormat, setExportingFormat] = useState<ExportFormat | null>(null);

	const handleExport = async (format: ExportFormat) => {
		setExportingFormat(format);
		try {
			await crmApi.exportQuote(quoteId, format);
		} catch {
			toast.error(t('errors.operationFailed'));
		} finally {
			setExportingFormat(null);
		}
	};

	const isExporting = exportingFormat !== null;

	return (
		<DropdownMenu>
			<DropdownMenuTrigger asChild>
				<Button size="sm" disabled={disabled || isExporting}>
					{isExporting ? <Loader2 className="size-3 animate-spin" /> : <Download className="size-3" />}
					{t('export.menu')}
				</Button>
			</DropdownMenuTrigger>
			<DropdownMenuContent align="end">
				<DropdownMenuItem disabled={isExporting} onSelect={() => handleExport('pdf')}>
					<FileText className="size-4" />
					{t('export.pdf')}
				</DropdownMenuItem>
				<DropdownMenuItem disabled={isExporting} onSelect={() => handleExport('xlsx')}>
					<FileSpreadsheet className="size-4" />
					{t('export.excel')}
				</DropdownMenuItem>
				<DropdownMenuItem disabled={isExporting} onSelect={() => handleExport('csv')}>
					<FileType className="size-4" />
					{t('export.csv')}
				</DropdownMenuItem>
			</DropdownMenuContent>
		</DropdownMenu>
	);
};
