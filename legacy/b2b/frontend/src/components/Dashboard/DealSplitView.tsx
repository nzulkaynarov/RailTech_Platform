import React, { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
    FileText,
    Plus,
    ChevronRight,
    Search,
    Clock,
    AlertCircle,
    MessageSquare,
    FolderOpen,
} from 'lucide-react';
import { crmApi, Deal } from '@/api/crmApi';
import { QuoteBuilderGrid } from '@/components/Admin/QuoteBuilderGrid';
import { ContextualChat } from '@/components/Dashboard/ContextualChat';
import { ExcelUpload } from '@/components/Sourcing/ExcelUpload';
import { formatMoney } from '@/utils/decimal';
import { cn } from '@/lib/utils';
import { useAuthStore } from '@/store/authStore';

import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import {
    Dialog,
    DialogTrigger,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogFooter,
    DialogDescription,
} from '@/components/ui/dialog';

type TabId = 'spec' | 'chat' | 'docs';

function getDealBadgeVariant(stage: string): 'default' | 'secondary' | 'destructive' | 'outline' {
    switch (stage) {
        case 'NEW':
            return 'secondary';
        case 'SOURCING':
        case 'CALCULATING':
            return 'outline';
        case 'QUOTE_SENT':
            return 'default';
        case 'CONTRACT_SIGNED':
            return 'default';
        case 'CLOSED_LOST':
            return 'destructive';
        default:
            return 'secondary';
    }
}

export const DealSplitView: React.FC = () => {
    const { t } = useTranslation();
    const [deals, setDeals] = useState<Deal[]>([]);
    const [selectedDealId, setSelectedDealId] = useState<number | null>(null);
    const [activeTab, setActiveTab] = useState<TabId>('spec');
    const [showUpload, setShowUpload] = useState(false);
    const [loading, setLoading] = useState(true);
    const [searchFilter, setSearchFilter] = useState('');
    const [isCreating, setIsCreating] = useState(false);
    const [newDealTitle, setNewDealTitle] = useState('');
    const [createDialogOpen, setCreateDialogOpen] = useState(false);
    const { role, user } = useAuthStore();
    // Stage workflow is a CRM action — visible to platform admin OR to a member
    // whose workspace_role inside the company is one of the management roles.
    // Maps to ADR-0002: SystemRole = ADMIN/USER, "manager" semantics live in
    // CompanyMember.role (WorkspaceRole).
    const wsRole = user?.workspace_role ?? null;
    const canManageStages = role === 'ADMIN' || (
        wsRole !== null && ['OWNER', 'SALES_MANAGER', 'CONTRACT_MANAGER', 'PROCUREMENT_MANAGER', 'BUYER_MANAGER'].includes(wsRole)
    );

    const handleCreateDeal = async () => {
        setIsCreating(true);
        try {
            const deal = await crmApi.createDeal({ title: newDealTitle || undefined });
            setNewDealTitle('');
            setCreateDialogOpen(false);
            await loadDeals();
            setSelectedDealId(deal.id);
        } catch (err) {
            const msg = err instanceof Error ? err.message : t('dashboard.deals.createError');
            toast.error(msg);
        } finally {
            setIsCreating(false);
        }
    };

    const handleStageChange = async (dealId: number, stageCode: string) => {
        try {
            await crmApi.changeDealStage(dealId, stageCode);
            await loadDeals();
        } catch (err) {
            toast.error(t('errors.operationFailed'));
        }
    };

    const loadDeals = useCallback(async (selectFirst = false) => {
        try {
            const data = await crmApi.getDeals();
            setDeals(data);
            if (selectFirst && data.length > 0 && !selectedDealId) {
                setSelectedDealId(data[0].id);
            }
        } catch {
            // Error handled via empty state
        } finally {
            setLoading(false);
        }
    }, [selectedDealId]);

    useEffect(() => {
        loadDeals(true);
    }, []);

    const selectedDeal = deals.find(d => d.id === selectedDealId);

    const filteredDeals = searchFilter
        ? deals.filter(d =>
            (d.company_name || '').toLowerCase().includes(searchFilter.toLowerCase()) ||
            d.id.toString().includes(searchFilter)
        )
        : deals;

    const stages = [
        { code: 'NEW', label: t('dealSplit.stages.NEW') },
        { code: 'SOURCING', label: t('dealSplit.stages.SOURCING') },
        { code: 'CALCULATING', label: t('dealSplit.stages.CALCULATING') },
        { code: 'QUOTE_SENT', label: t('dealSplit.stages.QUOTE_SENT') },
        { code: 'CONTRACT_SIGNED', label: t('dealSplit.stages.CONTRACT_SIGNED') },
        { code: 'CLOSED_LOST', label: t('dealSplit.stages.CLOSED_LOST') },
    ];

    if (loading) {
        return (
            <div className="flex h-[calc(100vh-52px)] rounded-lg overflow-hidden border bg-card">
                <div className="w-[300px] border-r p-3 space-y-3">
                    {Array.from({ length: 5 }).map((_, i) => (
                        <div key={i} className="space-y-2">
                            <Skeleton className="h-4 w-20" />
                            <Skeleton className="h-3 w-full" />
                            <Skeleton className="h-3 w-24" />
                        </div>
                    ))}
                </div>
                <div className="flex-1 flex items-center justify-center">
                    <div className="flex flex-col items-center gap-3">
                        <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                        <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="flex h-[calc(100vh-52px)] border bg-card rounded-lg overflow-hidden shadow-sm">
            {/* ─── Master List (Left Panel) ─── */}
            <div className="w-[300px] border-r flex flex-col bg-muted/30 shrink-0">
                {/* Search */}
                <div className="p-2.5 border-b bg-card">
                    <div className="relative">
                        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" aria-hidden="true" />
                        <Input
                            type="search"
                            value={searchFilter}
                            onChange={e => setSearchFilter(e.target.value)}
                            placeholder={t('common.search') + '...'}
                            aria-label={t('common.search')}
                            className="h-8 pl-9 text-sm"
                        />
                    </div>
                </div>

                {/* Deal list */}
                <ScrollArea className="flex-1" role="listbox" aria-label={t('dashboard.deals.title')}>
                    {filteredDeals.length === 0 ? (
                        <div className="flex flex-col items-center justify-center py-8 px-4 text-center">
                            <FileText className="w-8 h-8 text-muted-foreground mb-3" />
                            <p className="text-sm font-medium text-muted-foreground">{t('dashboard.deals.emptyState')}</p>
                            <p className="text-xs text-muted-foreground mt-1">{t('dashboard.deals.emptyStateHint')}</p>
                        </div>
                    ) : (
                        filteredDeals.map(deal => (
                            <Card
                                key={deal.id}
                                role="option"
                                aria-selected={selectedDealId === deal.id}
                                onClick={() => setSelectedDealId(deal.id)}
                                className={cn(
                                    'rounded-none border-x-0 border-t-0 py-3 px-3 gap-1.5 cursor-pointer transition-all relative group shadow-none',
                                    selectedDealId === deal.id
                                        ? 'bg-card border-l-4 border-l-primary'
                                        : 'hover:bg-accent/50 border-l-4 border-l-transparent',
                                )}
                            >
                                <div className="flex justify-between items-start">
                                    <span className="text-xs font-mono text-muted-foreground">#{deal.id}</span>
                                    <Badge variant={getDealBadgeVariant(String(deal.stage || 'NEW'))}>
                                        {deal.stage_name || t('dashboard.stages.NEW')}
                                    </Badge>
                                </div>
                                <div className="text-sm font-semibold text-foreground truncate">
                                    {deal.company_name || t('dashboard.deals.title')}
                                </div>
                                <div className="flex justify-between items-center text-xs">
                                    <div className="flex items-center gap-1 text-muted-foreground">
                                        <Clock size={12} />
                                        <span>{new Date(deal.created_at).toLocaleDateString()}</span>
                                    </div>
                                    <span className="font-mono font-semibold text-foreground/70">
                                        {formatMoney(deal.total_value)}
                                    </span>
                                </div>
                                <ChevronRight
                                    className={cn(
                                        'absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 transition-opacity',
                                        selectedDealId === deal.id ? 'opacity-100 text-primary' : 'opacity-0 group-hover:opacity-40',
                                    )}
                                />
                            </Card>
                        ))
                    )}
                </ScrollArea>

                <Separator />

                {/* Create deal */}
                <div className="p-2.5 bg-card space-y-2">
                    <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
                        <DialogTrigger asChild>
                            <Button className="w-full" size="sm">
                                <Plus size={16} />
                                {t('dashboard.deals.createRFQ')}
                            </Button>
                        </DialogTrigger>
                        <DialogContent>
                            <DialogHeader>
                                <DialogTitle>{t('dashboard.deals.createRFQ')}</DialogTitle>
                                <DialogDescription>
                                    {t('dashboard.deals.emptyStateHint')}
                                </DialogDescription>
                            </DialogHeader>
                            <Input
                                value={newDealTitle}
                                onChange={e => setNewDealTitle(e.target.value)}
                                placeholder={t('dashboard.deals.title') + '...'}
                                onKeyDown={e => e.key === 'Enter' && handleCreateDeal()}
                            />
                            <DialogFooter>
                                <Button variant="outline" onClick={() => setCreateDialogOpen(false)}>
                                    {t('common.cancel')}
                                </Button>
                                <Button onClick={handleCreateDeal} disabled={isCreating}>
                                    <Plus size={16} />
                                    {isCreating ? t('common.loading') : t('dashboard.deals.createRFQ')}
                                </Button>
                            </DialogFooter>
                        </DialogContent>
                    </Dialog>
                </div>
            </div>

            {/* ─── Detail View (Right Panel) ─── */}
            <div className="flex-1 flex flex-col min-w-0 bg-card">
                {selectedDeal ? (
                    <Tabs
                        value={activeTab}
                        onValueChange={(val) => setActiveTab(val as TabId)}
                        className="flex-1 flex flex-col gap-0 overflow-hidden"
                    >
                        {/* Header with tabs */}
                        <div className="h-11 border-b px-3 flex items-center justify-between shrink-0">
                            <div className="flex items-center gap-3 min-w-0">
                                <h2 className="text-sm font-bold text-foreground truncate">
                                    {selectedDeal.company_name || t('dashboard.deals.title')} #{selectedDeal.id}
                                </h2>
                                {activeTab === 'spec' && (
                                    <Button
                                        variant="link"
                                        size="xs"
                                        onClick={() => setShowUpload(!showUpload)}
                                        className="whitespace-nowrap"
                                    >
                                        {showUpload ? t('common.cancel') : t('dashboard.deals.bulkImport')}
                                    </Button>
                                )}
                            </div>

                            <TabsList className="shrink-0">
                                <TabsTrigger value="spec">
                                    <FileText size={14} />
                                    <span className="hidden sm:inline">{t('quote.title')}</span>
                                </TabsTrigger>
                                <TabsTrigger value="chat">
                                    <MessageSquare size={14} />
                                    <span className="hidden sm:inline">{t('chat.title')}</span>
                                </TabsTrigger>
                                <TabsTrigger value="docs">
                                    <FolderOpen size={14} />
                                    <span className="hidden sm:inline">{t('catalog.productDetail.documents')}</span>
                                </TabsTrigger>
                            </TabsList>
                        </div>

                        {/* Quote approval banner */}
                        {selectedDeal.stage_code === 'QUOTE_SENT' && (
                            <div className="bg-warning/10 border-b border-warning/20 px-4 py-2 flex items-center justify-between shrink-0">
                                <div className="flex items-center gap-2 text-warning text-sm font-medium">
                                    <AlertCircle size={16} />
                                    {t('quote.title')} — {t('dashboard.stages.QUOTING')}
                                </div>
                            </div>
                        )}

                        {/* Stage workflow (platform admin or company-side managers only) */}
                        {canManageStages && (
                            <div className="border-b px-3 py-1.5 flex items-center gap-1.5 shrink-0 overflow-x-auto bg-muted/50">
                                <span className="text-xs text-muted-foreground mr-1 shrink-0">{t('dealSplit.stageLabel')}:</span>
                                {stages.map(s => {
                                    const isActive = selectedDeal.stage_code === s.code;
                                    return (
                                        <Button
                                            key={s.code}
                                            variant={isActive ? 'default' : 'ghost'}
                                            size="xs"
                                            onClick={() => handleStageChange(selectedDeal.id, s.code)}
                                            className="whitespace-nowrap"
                                        >
                                            {s.label}
                                        </Button>
                                    );
                                })}
                            </div>
                        )}

                        {/* Content */}
                        <div className="flex-1 overflow-hidden flex flex-col">
                            {showUpload && (
                                <>
                                    <div className="p-3 bg-card shadow-sm">
                                        <ExcelUpload dealId={selectedDeal.id} onUploadSuccess={() => { setShowUpload(false); loadDeals(); }} />
                                    </div>
                                    <Separator />
                                </>
                            )}

                            <TabsContent value="spec" className="flex-1 overflow-hidden">
                                <QuoteBuilderGrid dealId={selectedDeal.id} />
                            </TabsContent>
                            <TabsContent value="chat" className="flex-1 overflow-hidden">
                                <ContextualChat dealId={selectedDeal.id} />
                            </TabsContent>
                            <TabsContent value="docs" className="flex-1 overflow-hidden">
                                <div className="flex flex-col items-center justify-center h-full p-8 text-center">
                                    <FolderOpen className="w-10 h-10 text-muted-foreground/50 mb-4" />
                                    <p className="text-sm font-semibold text-muted-foreground mb-2">{t('catalog.productDetail.documents')}</p>
                                    <p className="text-xs text-muted-foreground max-w-sm">
                                        {t('dealSplit.docsComingSoon')}
                                    </p>
                                </div>
                            </TabsContent>
                        </div>
                    </Tabs>
                ) : (
                    <div className="flex-1 flex flex-col items-center justify-center gap-3">
                        <FileText className="w-7 h-7 text-muted-foreground" />
                        <p className="text-sm text-muted-foreground">{t('dashboard.deals.noDealSelected')}</p>
                    </div>
                )}
            </div>
        </div>
    );
};
