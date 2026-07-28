import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Upload, Loader2, FileText } from 'lucide-react';
import { crmApi } from '@/api/crmApi';
import { translateApiError } from '@/lib/apiError';
import { Button } from '@/components/ui/button';
import {
	Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';

/**
 * Q2 — импорт позиций КП из файла (Excel/PDF/фото) через AI. Флагман запроса владельца:
 * продавец, получивший заявку файлом, добавляет её позиции в КП без ручного перебора.
 * Тот же 202+поллинг, что у покупательского импорта; Excel-вставка из буфера остаётся быстрым
 * путём. Паттерн Salesforce CPQ «Import Lines» (у них CSV; у нас vision — Excel/PDF/фото).
 */
const ACCEPT = '.xlsx,.xls,.csv,.tsv,.txt,.pdf,.png,.jpg,.jpeg,.webp,.gif';

export function ImportFileDialog({
	open, onOpenChange, quoteId,
}: {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	quoteId: number;
}) {
	const { t } = useTranslation();
	const queryClient = useQueryClient();
	const inputRef = useRef<HTMLInputElement>(null);
	const [file, setFile] = useState<File | null>(null);
	const [busy, setBusy] = useState(false);

	const reset = () => { setFile(null); setBusy(false); };

	const doImport = async () => {
		if (!file) return;
		setBusy(true);
		try {
			const result = await crmApi.importQuoteLinesFromFile(quoteId, file);
			await queryClient.invalidateQueries({ queryKey: ['quote-items'] });
			await queryClient.invalidateQueries({ queryKey: ['deals'] });
			if (result.added > 0) {
				toast.success(t('quoteImport.added', { count: result.added }));
				if (result.truncated) toast.warning(t('quoteImport.truncated', { count: result.added }));
			} else {
				toast.warning(t('quoteImport.none'));
			}
			onOpenChange(false);
			reset();
		} catch (e) {
			toast.error(translateApiError(e));
		} finally {
			setBusy(false);
		}
	};

	return (
		<Dialog open={open} onOpenChange={(o) => { onOpenChange(o); if (!o) reset(); }}>
			<DialogContent className="sm:max-w-md">
				<DialogHeader>
					<DialogTitle>{t('quoteImport.title')}</DialogTitle>
					<DialogDescription>{t('quoteImport.desc')}</DialogDescription>
				</DialogHeader>
				<input
					ref={inputRef}
					type="file"
					accept={ACCEPT}
					className="hidden"
					onChange={(e) => setFile(e.target.files?.[0] ?? null)}
				/>
				<button
					type="button"
					onClick={() => inputRef.current?.click()}
					disabled={busy}
					className="flex w-full flex-col items-center gap-2 rounded-lg border border-dashed border-input px-4 py-8 text-center text-sm transition-colors hover:bg-accent disabled:opacity-50"
				>
					{file ? (
						<>
							<FileText className="h-6 w-6 text-primary" aria-hidden="true" />
							<span className="font-medium">{file.name}</span>
							<span className="text-xs text-muted-foreground">{t('quoteImport.changeFile')}</span>
						</>
					) : (
						<>
							<Upload className="h-6 w-6 text-muted-foreground" aria-hidden="true" />
							<span>{t('quoteImport.pick')}</span>
							<span className="text-xs text-muted-foreground">{t('quoteImport.formats')}</span>
						</>
					)}
				</button>
				<DialogFooter>
					<Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
						{t('common.cancel')}
					</Button>
					<Button onClick={doImport} disabled={!file || busy}>
						{busy ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Upload className="mr-1.5 h-4 w-4" />}
						{busy ? t('quoteImport.importing') : t('quoteImport.import')}
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}
