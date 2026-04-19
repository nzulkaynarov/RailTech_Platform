import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
    LayoutDashboard, Users, Store, ShieldCheck, CreditCard, ClipboardList,
    Handshake, Layers, LifeBuoy, Package, Settings, HelpCircle, Building2,
    FolderTree, Boxes, Tag,
} from 'lucide-react';

import {
    CommandDialog, CommandInput, CommandList, CommandEmpty,
    CommandGroup, CommandItem, CommandSeparator,
} from '@/components/ui/command';

interface CommandPaletteProps {
    open: boolean;
    onOpenChange: (v: boolean) => void;
    onNavigate: (pageId: string) => void;
}

interface PaletteItem {
    id: string;
    labelKey: string;
    icon: React.ReactNode;
}

const ADMIN_GROUPS: { labelKey: string; items: PaletteItem[] }[] = [
    {
        labelKey: 'admin.palette.groups.overview',
        items: [
            { id: 'dashboard', labelKey: 'shell.dashboard', icon: <LayoutDashboard className="h-4 w-4" /> },
        ],
    },
    {
        labelKey: 'admin.palette.groups.users',
        items: [
            { id: 'admin-users', labelKey: 'shell.users', icon: <Users className="h-4 w-4" /> },
            { id: 'admin-companies', labelKey: 'shell.companies', icon: <Store className="h-4 w-4" /> },
            { id: 'admin-kyc', labelKey: 'shell.kyc', icon: <ShieldCheck className="h-4 w-4" /> },
            { id: 'admin-role-apps', labelKey: 'shell.roleApplications', icon: <ClipboardList className="h-4 w-4" /> },
            { id: 'admin-subscriptions', labelKey: 'shell.subscriptions', icon: <CreditCard className="h-4 w-4" /> },
        ],
    },
    {
        labelKey: 'admin.palette.groups.business',
        items: [
            { id: 'admin-deals', labelKey: 'shell.adminDeals', icon: <Handshake className="h-4 w-4" /> },
            { id: 'admin-support', labelKey: 'shell.support', icon: <LifeBuoy className="h-4 w-4" /> },
        ],
    },
    {
        labelKey: 'admin.palette.groups.catalog',
        items: [
            { id: 'admin-catalog', labelKey: 'shell.adminCatalogProducts', icon: <Package className="h-4 w-4" /> },
            { id: 'admin-categories', labelKey: 'shell.adminCatalogCategories', icon: <FolderTree className="h-4 w-4" /> },
            { id: 'admin-equipment-groups', labelKey: 'shell.adminCatalogGroups', icon: <Boxes className="h-4 w-4" /> },
            { id: 'admin-offers', labelKey: 'shell.adminCatalogOffers', icon: <Tag className="h-4 w-4" /> },
        ],
    },
    {
        labelKey: 'admin.palette.groups.system',
        items: [
            { id: 'admin-master-data', labelKey: 'shell.masterData', icon: <Layers className="h-4 w-4" /> },
            { id: 'settings', labelKey: 'shell.settings', icon: <Settings className="h-4 w-4" /> },
            { id: 'help', labelKey: 'shell.help', icon: <HelpCircle className="h-4 w-4" /> },
            { id: 'profile', labelKey: 'shell.profile', icon: <Building2 className="h-4 w-4" /> },
        ],
    },
];

export function CommandPalette({ open, onOpenChange, onNavigate }: CommandPaletteProps) {
    const { t } = useTranslation();

    const handleSelect = (id: string) => {
        onOpenChange(false);
        onNavigate(id);
    };

    return (
        <CommandDialog
            open={open}
            onOpenChange={onOpenChange}
            title={t('admin.palette.title')}
            description={t('admin.palette.description')}
        >
            <CommandInput placeholder={t('admin.palette.placeholder')} />
            <CommandList>
                <CommandEmpty>{t('admin.palette.empty')}</CommandEmpty>
                {ADMIN_GROUPS.map((group, groupIdx) => (
                    <div key={group.labelKey}>
                        {groupIdx > 0 && <CommandSeparator />}
                        <CommandGroup heading={t(group.labelKey)}>
                            {group.items.map((item) => (
                                <CommandItem
                                    key={item.id}
                                    value={`${t(item.labelKey)} ${item.id}`}
                                    onSelect={() => handleSelect(item.id)}
                                >
                                    {item.icon}
                                    <span>{t(item.labelKey)}</span>
                                </CommandItem>
                            ))}
                        </CommandGroup>
                    </div>
                ))}
            </CommandList>
        </CommandDialog>
    );
}

export function useCommandPaletteShortcut(onOpen: () => void) {
    useEffect(() => {
        const handler = (e: KeyboardEvent) => {
            if ((e.key === 'k' || e.key === 'K') && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                onOpen();
            }
        };
        window.addEventListener('keydown', handler);
        return () => window.removeEventListener('keydown', handler);
    }, [onOpen]);
}

export function CommandPaletteTrigger({ onOpen }: { onOpen: () => void }) {
    const { t } = useTranslation();
    return (
        <button
            type="button"
            onClick={onOpen}
            className="inline-flex items-center gap-2 rounded-md border bg-background px-2.5 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
            <span>{t('admin.palette.triggerHint')}</span>
            <kbd className="pointer-events-none hidden items-center gap-1 rounded border bg-muted px-1.5 py-0.5 font-mono text-xs font-medium sm:inline-flex">
                <span className="text-xs">⌘</span>K
            </kbd>
        </button>
    );
}

export function useCommandPaletteState(): [boolean, (v: boolean) => void, () => void] {
    const [open, setOpen] = useState(false);
    const openPalette = () => setOpen(true);
    return [open, setOpen, openPalette];
}
