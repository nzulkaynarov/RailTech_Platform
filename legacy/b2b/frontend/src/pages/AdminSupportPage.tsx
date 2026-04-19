import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
    LifeBuoy, MessageSquare, Send, UserCheck, Lock, Mail,
} from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import {
    Table, TableBody, TableCell, TableHeader, TableRow,
} from '@/components/ui/table';
import {
    Sheet, SheetContent, SheetHeader, SheetTitle,
} from '@/components/ui/sheet';
import {
    Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';

import {
    useSupportTickets,
    useSupportTicket,
    useSupportTicketMessages,
    useAddSupportMessage,
    useChangeSupportStatus,
    useAssignSupportTicket,
} from '@/hooks/useSupport';
import type {
    SupportTicket,
    SupportTicketStatus,
    SupportTicketPriority,
    SupportTicketCategory,
    SupportTicketListParams,
} from '@/api/supportApi';
import {
    Toolbar, SortableHead, Pager, useListParams,
} from '@/components/DataTable';
import { PageShell, LoadingRows, EmptyState } from './shared/PageShell';

const STATUS_FILTERS: SupportTicketStatus[] = ['OPEN', 'IN_PROGRESS', 'RESOLVED', 'CLOSED'];
const PRIORITY_FILTERS: SupportTicketPriority[] = ['LOW', 'NORMAL', 'HIGH', 'URGENT'];
const CATEGORY_FILTERS: SupportTicketCategory[] = ['BUG', 'QUESTION', 'BILLING', 'FEATURE', 'OTHER'];

function statusVariant(status: SupportTicketStatus): 'default' | 'secondary' | 'outline' | 'destructive' {
    switch (status) {
        case 'OPEN': return 'destructive';
        case 'IN_PROGRESS': return 'default';
        case 'RESOLVED': return 'secondary';
        case 'CLOSED': return 'outline';
    }
}

function priorityVariant(priority: SupportTicketPriority): 'default' | 'secondary' | 'outline' | 'destructive' {
    switch (priority) {
        case 'URGENT': return 'destructive';
        case 'HIGH': return 'default';
        case 'NORMAL': return 'secondary';
        case 'LOW': return 'outline';
    }
}

function TicketDetailSheet({
    ticketId, open, onOpenChange,
}: {
    ticketId: number | null;
    open: boolean;
    onOpenChange: (v: boolean) => void;
}) {
    const { t } = useTranslation();
    const { data: ticket, isLoading } = useSupportTicket(ticketId);
    const { data: messages } = useSupportTicketMessages(ticketId);
    const addMessage = useAddSupportMessage();
    const changeStatus = useChangeSupportStatus();
    const assign = useAssignSupportTicket();
    const [text, setText] = useState('');
    const [isInternal, setIsInternal] = useState(false);

    if (!ticketId) return null;

    const handleSend = async () => {
        const trimmed = text.trim();
        if (!trimmed || !ticketId) return;
        try {
            await addMessage.mutateAsync({ ticketId, text: trimmed, isInternal });
            setText('');
            setIsInternal(false);
            toast.success(t('admin.support.toast.messageSent'));
        } catch {
            toast.error(t('common.error'));
        }
    };

    const handleStatusChange = async (status: SupportTicketStatus) => {
        if (!ticketId) return;
        try {
            await changeStatus.mutateAsync({ ticketId, status });
            toast.success(t('admin.support.toast.statusChanged'));
        } catch {
            toast.error(t('common.error'));
        }
    };

    const handleAssignToMe = async () => {
        if (!ticketId) return;
        try {
            await assign.mutateAsync({ ticketId });
            toast.success(t('admin.support.toast.assigned'));
        } catch {
            toast.error(t('common.error'));
        }
    };

    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent className="overflow-y-auto sm:max-w-2xl">
                <SheetHeader>
                    <SheetTitle>
                        {ticket ? `#${ticket.id} ${ticket.subject}` : t('admin.support.detail.title')}
                    </SheetTitle>
                </SheetHeader>

                {isLoading || !ticket ? (
                    <div className="p-4">
                        <LoadingRows rows={5} />
                    </div>
                ) : (
                    <div className="mt-2 flex flex-col gap-6 px-4 pb-6">
                        <section className="space-y-3">
                            <div className="flex flex-wrap items-center gap-2">
                                <Badge variant={statusVariant(ticket.status)}>
                                    {t(`admin.support.status.${ticket.status}`)}
                                </Badge>
                                <Badge variant={priorityVariant(ticket.priority)}>
                                    {t(`admin.support.priority.${ticket.priority}`)}
                                </Badge>
                                <Badge variant="outline">
                                    {t(`admin.support.category.${ticket.category}`)}
                                </Badge>
                            </div>
                            <div className="rounded-lg border p-3 space-y-1 text-sm">
                                <p className="flex items-center gap-2 text-muted-foreground">
                                    <Mail className="h-3.5 w-3.5" />
                                    {ticket.created_by_full_name || ticket.created_by_email}
                                    {ticket.company_name && (
                                        <span className="text-xs">· {ticket.company_name}</span>
                                    )}
                                </p>
                                <p className="whitespace-pre-wrap text-foreground">
                                    {ticket.description}
                                </p>
                            </div>
                        </section>

                        <Separator />

                        <section className="space-y-3">
                            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                                <div className="space-y-1">
                                    <Label>{t('admin.support.detail.status')}</Label>
                                    <Select
                                        value={ticket.status}
                                        onValueChange={(v) => handleStatusChange(v as SupportTicketStatus)}
                                    >
                                        <SelectTrigger>
                                            <SelectValue />
                                        </SelectTrigger>
                                        <SelectContent>
                                            {STATUS_FILTERS.map((s) => (
                                                <SelectItem key={s} value={s}>
                                                    {t(`admin.support.status.${s}`)}
                                                </SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                </div>
                                <div className="space-y-1">
                                    <Label>{t('admin.support.detail.assigned')}</Label>
                                    <div className="flex items-center gap-2">
                                        <span className="flex-1 text-sm text-muted-foreground truncate">
                                            {ticket.assigned_to_email || t('admin.support.detail.unassigned')}
                                        </span>
                                        <Button
                                            size="sm"
                                            variant="outline"
                                            onClick={handleAssignToMe}
                                            disabled={assign.isPending}
                                        >
                                            <UserCheck className="h-3.5 w-3.5 mr-1" />
                                            {t('admin.support.detail.assignToMe')}
                                        </Button>
                                    </div>
                                </div>
                            </div>
                        </section>

                        <Separator />

                        <section className="space-y-3">
                            <h3 className="text-sm font-semibold flex items-center gap-2">
                                <MessageSquare className="h-4 w-4" />
                                {t('admin.support.detail.messages')}
                            </h3>
                            <div className="space-y-3">
                                {(messages ?? []).length === 0 ? (
                                    <p className="text-sm text-muted-foreground">
                                        {t('admin.support.detail.noMessages')}
                                    </p>
                                ) : (
                                    messages!.map((m) => (
                                        <div
                                            key={m.id}
                                            className={`rounded-lg border p-3 ${m.is_internal ? 'bg-warning/10 border-warning/40' : m.author_is_admin ? 'bg-primary/5' : 'bg-muted/40'}`}
                                        >
                                            <div className="flex items-center justify-between text-xs text-muted-foreground mb-1">
                                                <div className="flex items-center gap-1">
                                                    {m.is_internal && <Lock className="h-3 w-3" />}
                                                    <span>{m.author_full_name || m.author_email}</span>
                                                    {m.author_is_admin && (
                                                        <Badge variant="outline" className="h-4 px-1 text-xs">
                                                            {t('admin.support.detail.adminBadge')}
                                                        </Badge>
                                                    )}
                                                </div>
                                                <span>{new Date(m.created_at).toLocaleString()}</span>
                                            </div>
                                            <p className="whitespace-pre-wrap text-sm">{m.text}</p>
                                        </div>
                                    ))
                                )}
                            </div>
                        </section>

                        <Separator />

                        <section className="space-y-2">
                            <Label>{t('admin.support.detail.reply')}</Label>
                            <Textarea
                                value={text}
                                onChange={(e) => setText(e.target.value)}
                                placeholder={t('admin.support.detail.replyPlaceholder')}
                                rows={4}
                            />
                            <div className="flex items-center justify-between">
                                <div className="flex items-center gap-2">
                                    <Switch
                                        id="is-internal"
                                        checked={isInternal}
                                        onCheckedChange={setIsInternal}
                                    />
                                    <Label htmlFor="is-internal" className="text-sm font-normal flex items-center gap-1">
                                        <Lock className="h-3 w-3" />
                                        {t('admin.support.detail.internalNote')}
                                    </Label>
                                </div>
                                <Button
                                    onClick={handleSend}
                                    disabled={!text.trim() || addMessage.isPending}
                                >
                                    <Send className="h-4 w-4 mr-2" />
                                    {t('admin.support.detail.send')}
                                </Button>
                            </div>
                        </section>
                    </div>
                )}
            </SheetContent>
        </Sheet>
    );
}

export function AdminSupportPage() {
    const { t } = useTranslation();
    const {
        searchInput, setSearchInput, search,
        filters, setFilter,
        ordering, toggleOrdering,
        page, setPage, pageSize,
    } = useListParams(['status', 'priority', 'category'] as const, {
        defaultOrdering: '-created_at',
    });

    const queryParams: SupportTicketListParams = {
        search: search || undefined,
        status: filters.status !== 'all' ? (filters.status as SupportTicketStatus) : undefined,
        priority: filters.priority !== 'all' ? (filters.priority as SupportTicketPriority) : undefined,
        category: filters.category !== 'all' ? (filters.category as SupportTicketCategory) : undefined,
        ordering: ordering || undefined,
        page,
        page_size: pageSize,
    };

    const { data, isLoading } = useSupportTickets(queryParams);
    const tickets: SupportTicket[] = data?.results ?? [];
    const total = data?.count ?? 0;

    const [detailId, setDetailId] = useState<number | null>(null);

    const openCount = tickets.filter((x) => x.status === 'OPEN').length;
    const inProgressCount = tickets.filter((x) => x.status === 'IN_PROGRESS').length;
    const urgentCount = tickets.filter(
        (x) => x.priority === 'URGENT' && x.status !== 'CLOSED' && x.status !== 'RESOLVED',
    ).length;

    const stats = [
        { label: t('admin.support.stats.total'), value: String(total) },
        { label: t('admin.support.stats.open'), value: String(openCount) },
        { label: t('admin.support.stats.inProgress'), value: String(inProgressCount) },
        { label: t('admin.support.stats.urgent'), value: String(urgentCount) },
    ];

    return (
        <PageShell
            title={t('admin.support.title')}
            description={t('admin.support.description')}
            icon={<LifeBuoy className="h-5 w-5" />}
            stats={stats}
        >
            <Card>
                <CardContent className="flex flex-col gap-3 p-4">
                    <Toolbar
                        searchValue={searchInput}
                        onSearchChange={setSearchInput}
                        searchPlaceholder={t('admin.support.searchPlaceholder')}
                        filters={[
                            {
                                key: 'status',
                                value: filters.status,
                                onChange: (v) => setFilter('status', v),
                                allLabel: t('admin.support.filters.allStatuses'),
                                options: STATUS_FILTERS.map((s) => ({
                                    value: s,
                                    label: t(`admin.support.status.${s}`),
                                })),
                            },
                            {
                                key: 'priority',
                                value: filters.priority,
                                onChange: (v) => setFilter('priority', v),
                                allLabel: t('admin.support.filters.allPriorities'),
                                options: PRIORITY_FILTERS.map((p) => ({
                                    value: p,
                                    label: t(`admin.support.priority.${p}`),
                                })),
                            },
                            {
                                key: 'category',
                                value: filters.category,
                                onChange: (v) => setFilter('category', v),
                                allLabel: t('admin.support.filters.allCategories'),
                                options: CATEGORY_FILTERS.map((c) => ({
                                    value: c,
                                    label: t(`admin.support.category.${c}`),
                                })),
                            },
                        ]}
                    />

                    {isLoading ? (
                        <LoadingRows rows={6} />
                    ) : tickets.length === 0 ? (
                        <EmptyState
                            icon={<LifeBuoy className="h-5 w-5" />}
                            message={t('admin.support.empty')}
                        />
                    ) : (
                        <Table>
                            <TableHeader>
                                <TableRow>
                                    <SortableHead sortKey="id" current={ordering} onChange={toggleOrdering}>
                                        {t('admin.support.table.id')}
                                    </SortableHead>
                                    <SortableHead sortKey="subject" current={ordering} onChange={toggleOrdering}>
                                        {t('admin.support.table.subject')}
                                    </SortableHead>
                                    <SortableHead sortKey="status" current={ordering} onChange={toggleOrdering}>
                                        {t('admin.support.table.status')}
                                    </SortableHead>
                                    <SortableHead sortKey="priority" current={ordering} onChange={toggleOrdering}>
                                        {t('admin.support.table.priority')}
                                    </SortableHead>
                                    <SortableHead sortKey="created_at" current={ordering} onChange={toggleOrdering}>
                                        {t('admin.support.table.createdAt')}
                                    </SortableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {tickets.map((t_) => (
                                    <TableRow
                                        key={t_.id}
                                        className="cursor-pointer"
                                        onClick={() => setDetailId(t_.id)}
                                    >
                                        <TableCell className="tabular-nums">#{t_.id}</TableCell>
                                        <TableCell>
                                            <div>
                                                <span className="font-medium">{t_.subject}</span>
                                                <span className="block text-xs text-muted-foreground">
                                                    {t_.created_by_full_name || t_.created_by_email}
                                                </span>
                                            </div>
                                        </TableCell>
                                        <TableCell>
                                            <Badge variant={statusVariant(t_.status)}>
                                                {t(`admin.support.status.${t_.status}`)}
                                            </Badge>
                                        </TableCell>
                                        <TableCell>
                                            <Badge variant={priorityVariant(t_.priority)}>
                                                {t(`admin.support.priority.${t_.priority}`)}
                                            </Badge>
                                        </TableCell>
                                        <TableCell className="text-xs text-muted-foreground">
                                            {new Date(t_.created_at).toLocaleString()}
                                        </TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    )}

                    <Pager page={page} pageSize={pageSize} total={total} onPageChange={setPage} />
                </CardContent>
            </Card>

            <TicketDetailSheet
                ticketId={detailId}
                open={!!detailId}
                onOpenChange={(v) => { if (!v) setDetailId(null); }}
            />
        </PageShell>
    );
}

export default AdminSupportPage;
