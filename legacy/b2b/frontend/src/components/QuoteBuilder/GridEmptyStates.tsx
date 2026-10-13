/**
 * Два ранних экрана конструктора КП: загрузка и «активного КП ещё нет».
 *
 * Вынесено из QuoteBuilderGrid — это чистая презентация, которая раньше занимала ~45 строк
 * посреди оркестратора и мешала читать основной поток.
 *
 * Экран «нет КП» — НЕ тупик (Q1): у него есть первичное действие, открывающее создание КП,
 * поэтому продавец не упирается в кнопку «Назад».
 */

import { useTranslation } from 'react-i18next';
import { Loader2, Sparkles, FileText } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

export function GridLoadingSkeleton() {
	return (
		<Card className="min-h-[200px]">
			<CardContent className="flex flex-col items-center justify-center gap-4 py-12">
				<Skeleton className="h-8 w-full max-w-md" />
				<Skeleton className="h-6 w-full max-w-lg" />
				<Skeleton className="h-6 w-full max-w-lg" />
				<Skeleton className="h-6 w-full max-w-lg" />
				<Skeleton className="h-6 w-3/4 max-w-sm" />
			</CardContent>
		</Card>
	);
}

interface GridNoQuoteStateProps {
	dealId: number;
	draftBusy: boolean;
	onGenerateDraft: () => void;
	onOpenGenerateDialog: () => void;
}

export function GridNoQuoteState({ dealId, draftBusy, onGenerateDraft, onOpenGenerateDialog }: GridNoQuoteStateProps) {
	const { t } = useTranslation();
	return (
		<Card className="min-h-[200px]">
			<CardContent className="flex flex-col items-center justify-center gap-3 py-12 text-center">
				<div className="flex size-12 items-center justify-center rounded-full bg-muted">
					<FileText className="size-6 text-muted-foreground" aria-hidden="true" />
				</div>
				<h3 className="text-base font-semibold">{t('quote.empty.title')}</h3>
				<p className="max-w-sm text-sm text-muted-foreground">{t('quote.empty.description')}</p>
				<div className="mt-2 flex flex-wrap items-center justify-center gap-2">
					<Button onClick={onGenerateDraft} disabled={!dealId || draftBusy}>
						{draftBusy ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" aria-hidden="true" />}
						{t('aiDraft.action')}
					</Button>
					<Button variant="outline" onClick={onOpenGenerateDialog} disabled={!dealId}>
						<FileText className="size-4" aria-hidden="true" />
						{t('quote.empty.action')}
					</Button>
				</div>
			</CardContent>
		</Card>
	);
}
