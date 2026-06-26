import React, { useState, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { QuoteItem, crmApi } from '@/api/crmApi';
import { Loader2, Save, FileDown, AlertTriangle, Plus, Trash2, Sparkles, FileText, Settings } from 'lucide-react';
import { useQuoteItems, useUpdateQuoteItem, useCreateQuoteItem, useDeleteQuoteItem, useDeal, useSetQuoteDeliveryBasis } from '@/hooks/useCRM';
import { formatMoney, calculateLineTotal } from '@/utils/decimal';
import { DeliveryBasisSelect } from '@/components/CRM/DeliveryBasisSelect';
import { QuoteChargesSection } from '@/components/CRM/QuoteChargesSection';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from '@/components/ui/tooltip';
import { Separator } from '@/components/ui/separator';
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert';
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { QuoteApprovalChain } from '@/components/CRM/QuoteApprovalChain';
import { AICatalogMatchDialog } from '@/components/Admin/AICatalogMatchDialog';
import { GenerateQuoteDialog } from '@/components/CRM/GenerateQuoteDialog';
import { QuoteSettingsDialog } from '@/components/CRM/QuoteSettingsDialog';

interface QuoteBuilderGridProps {
	dealId?: number;
	onSave?: () => void;
}

export const QuoteBuilderGrid: React.FC<QuoteBuilderGridProps> = ({ dealId: propDealId, onSave }) => {
	const { t } = useTranslation();
	const dealId = propDealId || 0;

	const { data: quoteItems = [], isLoading: itemsLoading } = useQuoteItems({ deal_id: dealId });
	const { data: deal, isLoading: dealLoading } = useDeal(dealId);
	const updateMutation = useUpdateQuoteItem();
	const createItemMutation = useCreateQuoteItem();
	const deleteItemMutation = useDeleteQuoteItem();
	const setBasisMutation = useSetQuoteDeliveryBasis();

	const [localItems, setLocalItems] = useState<QuoteItem[]>([]);
	const [isExporting, setIsExporting] = useState(false);
	const [newItemName, setNewItemName] = useState('');
	const [showAddRow, setShowAddRow] = useState(false);
	const [showAiMatch, setShowAiMatch] = useState(false);
	const [showGenerateQuote, setShowGenerateQuote] = useState(false);
	const [showSettings, setShowSettings] = useState(false);

	useEffect(() => {
		if (quoteItems) {
			setLocalItems(quoteItems);
		}
	}, [quoteItems]);

	const hasUnsavedChanges = useMemo(() => {
		return JSON.stringify(localItems) !== JSON.stringify(quoteItems);
	}, [localItems, quoteItems]);

	const updateItemLocally = (id: number, field: keyof QuoteItem, value: string) => {
		setLocalItems(prev => prev.map(item => {
			if (item.id === id) {
				const cleanValue = value === '' ? "0" : value;
				return { ...item, [field]: cleanValue };
			}
			return item;
		}));
	};

	const handleSave = async () => {
		try {
			for (const item of localItems) {
				const original = quoteItems.find(oi => oi.id === item.id);
				if (JSON.stringify(item) !== JSON.stringify(original)) {
					await updateMutation.mutateAsync({
						id: item.id,
						data: {
							quantity: item.quantity,
							frozen_base_price: item.frozen_base_price,
							logistics_cost: item.logistics_cost,
							customs_duty: item.customs_duty,
							margin_percent: item.margin_percent,
							discount_percent: item.discount_percent,
							hs_code: item.hs_code,
						}
					});
				}
			}
			if (onSave) onSave();
		} catch {
			toast.error(t('errors.operationFailed'));
		}
	};

	const handleExport = async () => {
		setIsExporting(true);
		try {
			await crmApi.exportDealPDF(dealId);
		} catch {
			toast.error(t('errors.operationFailed'));
		} finally {
			setIsExporting(false);
		}
	};

	const handleAddItem = async () => {
		if (!newItemName.trim() || !deal?.active_quote) return;
		try {
			await createItemMutation.mutateAsync({
				quote: deal.active_quote.id,
				imported_raw_name: newItemName.trim(),
				quantity: 1,
				frozen_base_price: '0',
				frozen_currency: 'USD',
			});
			setNewItemName('');
			setShowAddRow(false);
		} catch {
			toast.error(t('errors.operationFailed'));
		}
	};

	const [deleteTarget, setDeleteTarget] = useState<number | null>(null);

	const handleDeleteItem = (id: number) => {
		setDeleteTarget(id);
	};

	const confirmDeleteItem = async () => {
		if (deleteTarget == null) return;
		try {
			await deleteItemMutation.mutateAsync(deleteTarget);
			setDeleteTarget(null);
		} catch {
			toast.error(t('errors.operationFailed'));
			setDeleteTarget(null);
		}
	};

	if (itemsLoading || dealLoading) {
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

	const activeQuote = deal?.active_quote;

	// No active quote → the grid has nothing to operate on. Show a guided
	// empty-state with a primary action that opens the existing КП-creation flow.
	if (!activeQuote) {
		return (
			<>
				<Card className="min-h-[200px]">
					<CardContent className="flex flex-col items-center justify-center gap-3 py-12 text-center">
						<div className="flex size-12 items-center justify-center rounded-full bg-muted">
							<FileText className="size-6 text-muted-foreground" aria-hidden="true" />
						</div>
						<h3 className="text-base font-semibold">{t('quote.empty.title')}</h3>
						<p className="max-w-sm text-sm text-muted-foreground">{t('quote.empty.description')}</p>
						<Button className="mt-2" onClick={() => setShowGenerateQuote(true)} disabled={!dealId}>
							<FileText className="size-4" aria-hidden="true" />
							{t('quote.empty.action')}
						</Button>
					</CardContent>
				</Card>
				<GenerateQuoteDialog
					dealId={dealId || null}
					open={showGenerateQuote}
					onOpenChange={setShowGenerateQuote}
				/>
			</>
		);
	}

	const currency = quoteItems[0]?.frozen_currency || 'USD';
	const vatRate = activeQuote?.vat_rate || '12';

	// Incoterm cost-responsibility flags drive cost-column visibility. With no basis
	// chosen yet, show all columns (don't hide already-entered data).
	// F3.8: the per-line table is UNIFIED across Incoterms. Only the customs duty (per ТНВЭД)
	// is a per-line cost; logistics/freight & everything else are document-level charges
	// (на всю партию) added below — driven by the chosen basis (per-basis ChargeTemplate),
	// not by per-line columns. So logistics never shows per-line; customs always does.
	const showLogistics = false;
	const showCustoms = true;

	const handleBasisChange = (basisId: number) => {
		if (!activeQuote) return;
		setBasisMutation.mutate({ id: activeQuote.id, deliveryBasis: basisId });
	};

	return (
		<div className="flex flex-col h-full gap-3">
			{/* КП internal approval chain (документооборот) */}
			{activeQuote && <QuoteApprovalChain quote={activeQuote} />}

			{/* Unsaved changes warning */}
			{hasUnsavedChanges && (
				<Alert>
					<AlertTriangle className="size-4" />
					<AlertTitle>{t('quote.unsavedChanges')}</AlertTitle>
					<AlertDescription>
						{t('quote.unsavedChangesDesc')}
					</AlertDescription>
				</Alert>
			)}

			{/* Toolbar */}
			<div className="flex items-center justify-between">
				<div className="flex items-center gap-3">
					<h2 className="text-sm font-bold">{t('quote.title')}</h2>
					<Separator orientation="vertical" className="h-4" />
					<DeliveryBasisSelect value={activeQuote?.delivery_basis} onChange={handleBasisChange} />
					<Badge variant="outline">{t('quote.vat')} {vatRate}%</Badge>
					<Badge variant="secondary">{currency}</Badge>
				</div>
				<div className="flex gap-1.5">
					{localItems.some(item => !item.product) && (
						<Button
							variant="outline"
							size="sm"
							onClick={() => setShowAiMatch(true)}
						>
							<Sparkles className="size-3" />
							{t('aiMatch.button')}
						</Button>
					)}
					<Button
						variant="outline"
						size="sm"
						onClick={() => setShowAddRow(!showAddRow)}
					>
						<Plus className="size-3" />
						{t('common.add')}
					</Button>
					{!activeQuote.frozen_at && (
						<Button
							variant="outline"
							size="sm"
							onClick={() => setShowSettings(true)}
						>
							<Settings className="size-3" />
							{t('quote.settings.title')}
						</Button>
					)}
					<Button
						variant="outline"
						size="sm"
						onClick={handleSave}
						disabled={updateMutation.isPending}
					>
						{updateMutation.isPending ? <Loader2 className="size-3 animate-spin" /> : <Save className="size-3" />}
						{t('common.save')}
					</Button>
					<Button
						size="sm"
						onClick={handleExport}
						disabled={isExporting}
					>
						{isExporting ? <Loader2 className="size-3 animate-spin" /> : <FileDown className="size-3" />}
						{t('quote.pdf')}
					</Button>
				</div>
			</div>

			<Separator />

			{/* Data Grid */}
			<div className="flex-1 overflow-auto rounded-md border">
				<TooltipProvider>
					<Table className="w-full text-left text-sm">
						<TableHeader className="sticky top-0 z-20 border-b bg-muted">
							<TableRow>
								<TableHead className="px-2 py-2 text-center text-xs font-semibold text-muted-foreground w-8 sticky left-0 z-30 bg-muted">#</TableHead>
								<TableHead className="px-2 py-2 text-xs font-semibold text-muted-foreground min-w-[200px] sticky left-8 z-30 bg-muted">
									{t('catalog.table.name')}
								</TableHead>
								<TableHead className="px-2 py-2 text-xs font-semibold text-muted-foreground w-28">
									<Tooltip>
										<TooltipTrigger asChild>
											<span className="cursor-help">{t('quote.hsCode')}</span>
										</TooltipTrigger>
										<TooltipContent>{t('quote.hsCodeHelp')}</TooltipContent>
									</Tooltip>
								</TableHead>
								<TableHead className="px-2 py-2 text-center text-xs font-semibold text-muted-foreground w-16">
									<Tooltip>
										<TooltipTrigger asChild>
											<span className="cursor-help">{t('quote.quantity')}</span>
										</TooltipTrigger>
										<TooltipContent>{t('quote.quantityHelp')}</TooltipContent>
									</Tooltip>
								</TableHead>
								<TableHead className="px-2 py-2 text-xs font-semibold text-muted-foreground w-28 bg-muted/30">
									<Tooltip>
										<TooltipTrigger asChild>
											<span className="cursor-help">{t('quote.basePrice')}</span>
										</TooltipTrigger>
										<TooltipContent>{t('quote.basePriceHelp')}</TooltipContent>
									</Tooltip>
								</TableHead>
								{showLogistics && (
									<TableHead className="px-2 py-2 text-xs font-semibold text-muted-foreground w-24 bg-muted/30">
										<Tooltip>
											<TooltipTrigger asChild>
												<span className="cursor-help">{t('quote.logistics')}</span>
											</TooltipTrigger>
											<TooltipContent>{t('quote.logisticsHelp')}</TooltipContent>
										</Tooltip>
									</TableHead>
								)}
								{showCustoms && (
									<TableHead className="px-2 py-2 text-xs font-semibold text-muted-foreground w-24 bg-muted/30">
										<Tooltip>
											<TooltipTrigger asChild>
												<span className="cursor-help">{t('quote.customsDuty')}</span>
											</TooltipTrigger>
											<TooltipContent>{t('quote.customsDutyHelp')}</TooltipContent>
										</Tooltip>
									</TableHead>
								)}
								<TableHead className="px-2 py-2 text-xs font-bold text-muted-foreground w-28">
									<Tooltip>
										<TooltipTrigger asChild>
											<span className="cursor-help">{t('quote.landedCost')}</span>
										</TooltipTrigger>
										<TooltipContent>{t('quote.landedCostHelp')}</TooltipContent>
									</Tooltip>
								</TableHead>
								<TableHead className="px-2 py-2 text-center text-xs font-semibold text-primary w-16">
									<Tooltip>
										<TooltipTrigger asChild>
											<span className="cursor-help">{t('quote.margin')}</span>
										</TooltipTrigger>
										<TooltipContent>{t('quote.marginHelp')}</TooltipContent>
									</Tooltip>
								</TableHead>
								<TableHead className="px-2 py-2 text-right text-xs font-semibold text-muted-foreground w-32 pr-4">
									{t('quote.lineTotal')}
								</TableHead>
								<TableHead className="px-2 py-2 w-8" />
							</TableRow>
						</TableHeader>
						<TableBody className="divide-y">
							{localItems.map((item, idx) => (
								<TableRow key={item.id} className="hover:bg-muted/50 transition-colors group">
									<TableCell className="px-2 py-1.5 text-center text-xs font-mono text-muted-foreground tabular-nums w-8 sticky left-0 z-10 bg-background group-hover:bg-muted/50">
										{idx + 1}
									</TableCell>
									<TableCell className="px-2 py-1.5 sticky left-8 z-10 bg-background group-hover:bg-muted/50">
										<div className="flex flex-col leading-tight pr-4">
											<div className="flex items-center gap-2">
												{!item.product && (
													<AlertTriangle className="size-3 text-warning shrink-0" aria-label={t('sourcing.noMatch')} />
												)}
												<span className="text-sm font-semibold truncate max-w-[280px]">
													{item.product_name || item.imported_raw_name}
												</span>
												{item.product_domain && (
													<Badge variant="outline" className="text-xs px-1.5 py-0">
														{item.product_domain}
													</Badge>
												)}
											</div>
											<span className="text-xs text-muted-foreground mt-0.5 truncate">
												{item.offer_supplier_name || t('sourcing.noMatch')}
											</span>
										</div>
									</TableCell>
									<TableCell className="p-0">
										<Input
											type="text"
											aria-label={t('quote.hsCode')}
											placeholder={t('quote.hsCode')}
											className="h-8 border-none shadow-none rounded-none text-xs font-mono text-center focus-visible:ring-1"
											value={item.hs_code || ''}
											onChange={(e) => updateItemLocally(item.id, 'hs_code', e.target.value)}
										/>
									</TableCell>
									<TableCell className="p-0">
										<Input
											type="number"
											aria-label={t('catalog.table.unit')}
											className="h-8 border-none shadow-none rounded-none text-xs font-semibold text-center focus-visible:ring-1"
											value={item.quantity}
											onChange={(e) => updateItemLocally(item.id, 'quantity', e.target.value)}
										/>
									</TableCell>
									<TableCell className="p-0 bg-muted/20">
										<Input
											type="number"
											aria-label={t('quote.basePrice')}
											className="h-8 border-none shadow-none rounded-none text-xs font-mono text-right pr-2 focus-visible:ring-1"
											value={item.frozen_base_price}
											onChange={(e) => updateItemLocally(item.id, 'frozen_base_price', e.target.value)}
										/>
									</TableCell>
									{showLogistics && (
										<TableCell className="p-0 bg-muted/20">
											<Input
												type="number"
												aria-label={t('quote.logistics')}
												className="h-8 border-none shadow-none rounded-none text-xs font-mono text-right pr-2 focus-visible:ring-1"
												value={item.logistics_cost}
												onChange={(e) => updateItemLocally(item.id, 'logistics_cost', e.target.value)}
											/>
										</TableCell>
									)}
									{showCustoms && (
										<TableCell className="p-0 bg-muted/20">
											<Input
												type="number"
												aria-label={t('quote.customsDuty')}
												className="h-8 border-none shadow-none rounded-none text-xs font-mono text-right pr-2 focus-visible:ring-1"
												value={item.customs_duty}
												onChange={(e) => updateItemLocally(item.id, 'customs_duty', e.target.value)}
											/>
										</TableCell>
									)}
									<TableCell className="px-2 py-1.5 text-right pr-2 bg-muted/30">
										<span className="text-sm font-bold tabular-nums">
											{formatMoney(item.landed_cost, item.frozen_currency)}
										</span>
									</TableCell>
									<TableCell className="p-0">
										<Input
											type="number"
											aria-label={t('quote.margin')}
											className="h-8 border-none shadow-none rounded-none text-xs font-bold text-center text-primary focus-visible:ring-1"
											value={item.margin_percent}
											onChange={(e) => updateItemLocally(item.id, 'margin_percent', e.target.value)}
										/>
									</TableCell>
									<TableCell className="px-2 py-1.5 text-right pr-4">
										<span className="text-sm font-bold tabular-nums">
											{formatMoney(calculateLineTotal(item.final_price_excl_vat, item.quantity), item.frozen_currency)}
										</span>
									</TableCell>
									<TableCell className="px-1 py-0.5">
										<Button
											variant="ghost"
											size="icon-xs"
											onClick={() => handleDeleteItem(item.id)}
											className="text-muted-foreground hover:text-destructive"
											title={t('common.delete')}
										>
											<Trash2 className="size-3" />
										</Button>
									</TableCell>
								</TableRow>
							))}
							{showAddRow && (
								<TableRow className="bg-primary/5">
									<TableCell className="px-2 py-1.5 text-center text-xs text-muted-foreground">+</TableCell>
									<TableCell className="p-1" colSpan={20}>
										<div className="flex items-center gap-2">
											<Input
												type="text"
												value={newItemName}
												onChange={e => setNewItemName(e.target.value)}
												onKeyDown={e => e.key === 'Enter' && handleAddItem()}
												placeholder={t('quote.addItemPlaceholder')}
												className="h-7 flex-1 text-sm"
												autoFocus
											/>
											<Button
												size="sm"
												onClick={handleAddItem}
												disabled={!newItemName.trim() || createItemMutation.isPending}
											>
												{t('common.add')}
											</Button>
										</div>
									</TableCell>
								</TableRow>
							)}
						</TableBody>
					</Table>
				</TooltipProvider>
			</div>

			<Separator />

			{/* КП-level expense items / discounts (seller-only) */}
			{activeQuote && <QuoteChargesSection quoteId={activeQuote.id} currency={currency} />}

			{/* Summary Footer */}
			<Card className="py-3">
				<CardContent className="flex items-center justify-end gap-6 py-0">
					<div className="flex flex-col items-end leading-none">
						<span className="text-xs text-muted-foreground mb-1">{t('quote.subtotal')}</span>
						<span className="text-sm font-semibold tabular-nums">
							{formatMoney(activeQuote?.subtotal_excl_vat)}
						</span>
					</div>
					{/* Show the charges line whenever КП-level charges EXIST — even when they net
					    to 0 (e.g. a +100 charge offset by a −100 discount). Keying off the net
					    total alone would hide that any charges were applied (charges-net-0). */}
					{activeQuote?.charges_total != null && (activeQuote.charges?.length ?? 0) > 0 && (
						<>
							<Separator orientation="vertical" className="h-6" />
							<div className="flex flex-col items-end leading-none">
								<span className="text-xs text-muted-foreground mb-1">{t('quote.charges.title')}</span>
								<span className="text-sm font-semibold tabular-nums">
									{formatMoney(activeQuote.charges_total)}
								</span>
							</div>
						</>
					)}
					<Separator orientation="vertical" className="h-6" />
					<div className="flex flex-col items-end leading-none">
						<span className="text-xs text-muted-foreground mb-1">{t('quote.vat')}</span>
						<span className="text-sm font-semibold tabular-nums">
							{formatMoney(activeQuote?.vat_amount)}
						</span>
					</div>
					<Separator orientation="vertical" className="h-8" />
					<div className="flex flex-col items-end leading-none">
						<span className="text-xs text-primary font-semibold mb-1">{t('quote.total')}</span>
						<span className="text-xl font-bold tabular-nums">
							{formatMoney(activeQuote?.total_incl_vat)}
						</span>
					</div>
				</CardContent>
			</Card>

			<AICatalogMatchDialog
				open={showAiMatch}
				onOpenChange={setShowAiMatch}
				items={localItems}
			/>

			<QuoteSettingsDialog
				quote={activeQuote}
				open={showSettings}
				onOpenChange={setShowSettings}
			/>

			<AlertDialog open={deleteTarget != null} onOpenChange={(o) => !o && setDeleteTarget(null)}>
				<AlertDialogContent>
					<AlertDialogHeader>
						<AlertDialogTitle>{t('quote.deleteItem')}</AlertDialogTitle>
						<AlertDialogDescription>{t('deleteConfirmations.quoteItemDescription')}</AlertDialogDescription>
					</AlertDialogHeader>
					<AlertDialogFooter>
						<AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
						<AlertDialogAction onClick={confirmDeleteItem} disabled={deleteItemMutation.isPending}>
							{t('common.delete')}
						</AlertDialogAction>
					</AlertDialogFooter>
				</AlertDialogContent>
			</AlertDialog>
		</div>
	);
};
