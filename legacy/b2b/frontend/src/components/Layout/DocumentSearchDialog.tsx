import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
    FileText, FileSignature, Receipt, ClipboardCheck, FileType, Loader2,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import {
    CommandDialog, CommandInput, CommandList, CommandEmpty,
    CommandGroup, CommandItem,
} from '@/components/ui/command';
import { Badge } from '@/components/ui/badge';
import { useSearchDocuments } from '@/hooks/usePageStats';
import type { RecentDocument } from '@/api/dashboardApi';

interface DocumentSearchDialogProps {
    open: boolean;
    onOpenChange: (v: boolean) => void;
    /**
     * Called with the document's ready-to-use SPA deep-link (the backend `hash`, e.g.
     * `deal-quote/5`, `invoices?open=3`, `other-documents`). Query-carrying hashes are
     * assigned to `window.location.hash` directly here, so the caller need not parse them.
     */
    onNavigate: (hash: string) => void;
}

// Mirrors the dashboard RecentDocumentsCard icon map (single source of truth for doc-type glyphs).
const DOC_TYPE_ICON: Record<RecentDocument['type'], LucideIcon> = {
    quote: FileText,
    contract: FileSignature,
    invoice: Receipt,
    act: ClipboardCheck,
    generated: FileType,
};

// Fixed render order for the result groups.
const DOC_TYPE_ORDER: RecentDocument['type'][] = ['quote', 'contract', 'invoice', 'act', 'generated'];

const MIN_CHARS = 2;
const DEBOUNCE_MS = 250;

export function DocumentSearchDialog({ open, onOpenChange, onNavigate }: DocumentSearchDialogProps) {
    const { t } = useTranslation();
    const [query, setQuery] = useState('');
    const debouncedQuery = useDebouncedValue(query, DEBOUNCE_MS);
    const term = debouncedQuery.trim();
    const search = useSearchDocuments(term);

    // Reset the input each time the dialog closes so a re-open starts clean.
    useEffect(() => {
        if (!open) setQuery('');
    }, [open]);

    const grouped = useMemo(() => {
        const results = search.data ?? [];
        const byType = new Map<RecentDocument['type'], RecentDocument[]>();
        for (const doc of results) {
            const bucket = byType.get(doc.type);
            if (bucket) bucket.push(doc);
            else byType.set(doc.type, [doc]);
        }
        return DOC_TYPE_ORDER
            .map((type) => ({ type, items: byType.get(type) ?? [] }))
            .filter((group) => group.items.length > 0);
    }, [search.data]);

    const handleSelect = (hash: string) => {
        onOpenChange(false);
        onNavigate(hash);
    };

    const isSearching = term.length >= MIN_CHARS;
    const hasResults = grouped.length > 0;

    return (
        <CommandDialog
            open={open}
            onOpenChange={onOpenChange}
            title={t('search.title')}
            description={t('search.description')}
            // cmdk filters items client-side by default; our results are already
            // server-filtered (matching on deal number, INN, etc. that need not appear in
            // the label), so we disable the double-filter by embedding the query in each
            // item value — every server row is therefore always shown.
        >
            <CommandInput
                placeholder={t('search.placeholder')}
                value={query}
                onValueChange={setQuery}
            />
            <CommandList>
                {!isSearching && (
                    <div className="py-6 text-center text-sm text-muted-foreground">
                        {t('search.minChars', { count: MIN_CHARS })}
                    </div>
                )}

                {isSearching && search.isLoading && (
                    <div className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground">
                        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                        <span>{t('common.loading')}</span>
                    </div>
                )}

                {isSearching && !search.isLoading && !hasResults && (
                    <CommandEmpty>{t('search.empty')}</CommandEmpty>
                )}

                {isSearching && hasResults && grouped.map((group) => {
                    const Icon = DOC_TYPE_ICON[group.type] ?? FileText;
                    return (
                        <CommandGroup key={group.type} heading={t(`search.groups.${group.type}`)}>
                            {group.items.map((doc) => (
                                <CommandItem
                                    key={`${doc.type}-${doc.id}`}
                                    // Embed the query so cmdk's built-in filter never hides a server match.
                                    value={`${doc.type}-${doc.id} ${doc.label} ${term}`}
                                    onSelect={() => handleSelect(doc.hash)}
                                >
                                    <Icon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                                    <div className="flex min-w-0 flex-1 flex-col">
                                        <span className="truncate">{doc.label}</span>
                                    </div>
                                    {doc.status_code && (
                                        <Badge variant="secondary" className="shrink-0">
                                            {t(`dashboardPage.recentDocuments.statusCode.${doc.status_code}`, {
                                                defaultValue: doc.status_code,
                                            })}
                                        </Badge>
                                    )}
                                    <span className="shrink-0 text-xs text-muted-foreground">
                                        {new Date(doc.date).toLocaleDateString()}
                                    </span>
                                </CommandItem>
                            ))}
                        </CommandGroup>
                    );
                })}
            </CommandList>
        </CommandDialog>
    );
}

function useDebouncedValue<T>(value: T, delayMs: number): T {
    const [debounced, setDebounced] = useState(value);
    useEffect(() => {
        const timer = setTimeout(() => setDebounced(value), delayMs);
        return () => clearTimeout(timer);
    }, [value, delayMs]);
    return debounced;
}
