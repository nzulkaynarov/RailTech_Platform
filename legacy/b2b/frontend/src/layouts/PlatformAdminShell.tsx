import { useMemo, useState } from 'react';
import {
  LayoutDashboard,
  Package,
  Settings,
  HelpCircle,
  Users,
  User,
  LogOut,
  ChevronUp,
  ChevronDown,
  Store,
  Handshake,
  FileText, FileSignature,
  ShieldCheck,
  CreditCard,
  ClipboardList,
  Layers,
  Building2,
  LifeBuoy,
  Mail,
} from 'lucide-react';

import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarRail,
  SidebarTrigger,
  useSidebar,
} from '@/components/ui/sidebar';

import { useTranslation } from 'react-i18next';
import { useUserStore } from '@/store/userStore';
import { useAuthStore } from '@/store/authStore';
import { NotificationCenter } from '@/components/Layout/NotificationCenter';
import {
  CommandPalette,
  CommandPaletteTrigger,
  useCommandPaletteShortcut,
} from '@/components/Layout/CommandPalette';
import { AdminShortcuts } from '@/components/Admin/AdminShortcuts';
import { usePlatformDashboard } from '@/hooks/usePageStats';

/* ─── Types ─────────────────────────────────────────────────────────── */

interface NavChild {
  label: string;
  id: string;
  active?: boolean;
}

interface NavItem {
  label: string;
  icon: React.ReactNode;
  id?: string;
  active?: boolean;
  badge?: number;
  children?: NavChild[];
}

type TFn = (key: string) => string;

interface AttentionCounts {
  kyc?: number;
  roleApps?: number;
  subsPastDue?: number;
  subsExpiring?: number;
  overdueInvoices?: number;
}

/* ─── Platform-admin-only navigation ────────────────────────────────── */

function getAdminNavigation(activePage: string, t: TFn, attention: AttentionCounts): NavItem[] {
  return [
    { label: t('shell.dashboard'), icon: <LayoutDashboard className="h-4 w-4" />, id: 'dashboard', active: activePage === 'dashboard' },
    { label: t('shell.users'), icon: <Users className="h-4 w-4" />, id: 'admin-users', active: activePage === 'admin-users' },
    { label: t('shell.companies'), icon: <Store className="h-4 w-4" />, id: 'admin-companies', active: activePage === 'admin-companies' },
    { label: t('shell.kyc'), icon: <ShieldCheck className="h-4 w-4" />, id: 'admin-kyc', active: activePage === 'admin-kyc', badge: attention.kyc },
    {
      label: t('shell.subscriptions'), icon: <CreditCard className="h-4 w-4" />, id: 'admin-subscriptions',
      active: activePage === 'admin-subscriptions',
      badge: (attention.subsPastDue ?? 0) + (attention.subsExpiring ?? 0) || undefined,
    },
    { label: t('shell.roleApplications'), icon: <ClipboardList className="h-4 w-4" />, id: 'admin-role-apps', active: activePage === 'admin-role-apps', badge: attention.roleApps },
    { label: t('shell.adminDeals'), icon: <Handshake className="h-4 w-4" />, id: 'admin-deals', active: activePage === 'admin-deals' },
    { label: t('shell.adminQuotes'), icon: <FileText className="h-4 w-4" />, id: 'crm-quotes', active: activePage === 'crm-quotes' },
    { label: t('shell.adminContracts'), icon: <FileSignature className="h-4 w-4" />, id: 'contracts', active: activePage === 'contracts' },
    { label: t('shell.masterData'), icon: <Layers className="h-4 w-4" />, id: 'admin-master-data', active: activePage === 'admin-master-data' },
    { label: t('shell.operatorRoles'), icon: <ShieldCheck className="h-4 w-4" />, id: 'admin-operator-roles', active: activePage === 'admin-operator-roles' },
    { label: t('shell.emailTemplates'), icon: <Mail className="h-4 w-4" />, id: 'admin-email-templates', active: activePage === 'admin-email-templates' },
    { label: t('shell.support'), icon: <LifeBuoy className="h-4 w-4" />, id: 'admin-support', active: activePage === 'admin-support' },
    {
      label: t('shell.adminCatalog'), icon: <Package className="h-4 w-4" />,
      children: [
        { label: t('shell.adminCatalogProducts'), id: 'admin-catalog', active: activePage === 'admin-catalog' },
        { label: t('shell.adminCatalogCategories'), id: 'admin-categories', active: activePage === 'admin-categories' },
        { label: t('shell.adminCatalogGroups'), id: 'admin-equipment-groups', active: activePage === 'admin-equipment-groups' },
        { label: t('shell.adminCatalogOffers'), id: 'admin-offers', active: activePage === 'admin-offers' },
      ],
    },
  ];
}

function getBottomNavigation(t: TFn): NavItem[] {
  return [
    { label: t('shell.settings'), icon: <Settings className="h-4 w-4" />, id: 'settings' },
    { label: t('shell.help'), icon: <HelpCircle className="h-4 w-4" />, id: 'help' },
  ];
}

/* ─── Nav item ──────────────────────────────────────────────────────── */

function SidebarNavItem({
  item, onNavigate, collapsed,
}: {
  item: NavItem;
  onNavigate: (id: string) => void;
  collapsed: boolean;
}) {
  const hasActiveChild = item.children?.some((c) => c.active) ?? false;
  const [open, setOpen] = useState(hasActiveChild);

  if (item.children) {
    // Radix `asChild` chains must forward to a single DOM element. Putting a
    // <Tooltip> provider between CollapsibleTrigger and <Button> breaks the
    // handler chain and the Button never receives the open-toggle onClick —
    // that's why the "Catalog" item in the sidebar was unclickable. Nesting
    // Tooltip outside Collapsible (and putting asChild on every link to a
    // single Button) fixes it.
    return (
      <Tooltip>
        <Collapsible open={open} onOpenChange={setOpen}>
          <TooltipTrigger asChild>
            <CollapsibleTrigger asChild>
              <Button
                variant="ghost"
                className={cn(
                  'flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors h-auto hover:bg-accent hover:text-accent-foreground',
                  hasActiveChild ? 'text-foreground' : 'text-muted-foreground',
                  collapsed && 'justify-center px-0',
                )}
              >
                {item.icon}
                {!collapsed && (
                  <>
                    <span className="flex-1 text-left truncate">{item.label}</span>
                    <ChevronDown className={cn('h-4 w-4 transition-transform', open && 'rotate-180')} aria-hidden="true" />
                  </>
                )}
              </Button>
            </CollapsibleTrigger>
          </TooltipTrigger>
          {collapsed && <TooltipContent side="right">{item.label}</TooltipContent>}
          {!collapsed && (
            <CollapsibleContent>
              <div className="ml-4 mt-1 flex flex-col gap-0.5 border-l pl-3">
                {item.children.map((child) => (
                  <Button
                    key={child.id}
                    variant="ghost"
                    className={cn(
                      'rounded-md px-3 py-1.5 text-left text-sm transition-colors hover:bg-accent hover:text-accent-foreground h-auto w-full justify-start',
                      child.active ? 'bg-accent font-medium text-foreground' : 'text-muted-foreground',
                    )}
                    onClick={() => onNavigate(child.id)}
                  >
                    {child.label}
                  </Button>
                ))}
              </div>
            </CollapsibleContent>
          )}
        </Collapsible>
      </Tooltip>
    );
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          className={cn(
            'flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors h-auto hover:bg-accent hover:text-accent-foreground',
            item.active ? 'bg-accent text-foreground' : 'text-muted-foreground',
            collapsed && 'justify-center px-0',
          )}
          onClick={() => item.id && onNavigate(item.id)}
        >
          {item.icon}
          {!collapsed && (
            <>
              <span className="flex-1 text-left truncate">{item.label}</span>
              {item.badge != null && item.badge > 0 && (
                <Badge variant="destructive" className="h-5 min-w-5 justify-center rounded-full px-1.5 text-xs tabular-nums">
                  {item.badge}
                </Badge>
              )}
            </>
          )}
        </Button>
      </TooltipTrigger>
      {collapsed && <TooltipContent side="right">{item.label}{item.badge ? ` (${item.badge})` : ''}</TooltipContent>}
    </Tooltip>
  );
}

/* ─── PlatformAdminShell ────────────────────────────────────────────── */

interface PlatformAdminShellProps {
  children: React.ReactNode;
  activePage: string;
  onNavigate: (target: string) => void;
}

export function PlatformAdminShell(props: PlatformAdminShellProps) {
  return (
    <SidebarProvider>
      <PlatformAdminShellInner {...props} />
    </SidebarProvider>
  );
}

function PlatformAdminShellInner({ children, activePage, onNavigate }: PlatformAdminShellProps) {
  const { t } = useTranslation();
  const { profile } = useUserStore();
  const { state } = useSidebar();
  const sidebarCollapsed = state === 'collapsed';
  const { data: platformDashboard } = usePlatformDashboard();
  const [paletteOpen, setPaletteOpen] = useState(false);
  useCommandPaletteShortcut(() => setPaletteOpen(true));

  const attention: AttentionCounts = useMemo(() => {
    const attentionData = platformDashboard?.attention;
    return {
      kyc: attentionData?.kyc || undefined,
      roleApps: attentionData?.role_applications || undefined,
      subsPastDue: attentionData?.subscriptions_past_due || undefined,
      subsExpiring: attentionData?.subscriptions_expiring_7d || undefined,
      overdueInvoices: attentionData?.overdue_invoices || undefined,
    };
  }, [platformDashboard]);

  const navigation = useMemo(() => getAdminNavigation(activePage, t, attention), [activePage, t, attention]);
  const bottomNav = useMemo(() => getBottomNavigation(t), [t]);

  return (
    <TooltipProvider>
      <Sidebar collapsible="icon">
        <SidebarHeader>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton size="lg" onClick={() => onNavigate('dashboard')}>
                <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                  <Building2 className="size-4" />
                </div>
                <div className="grid flex-1 text-left text-sm leading-tight">
                  <span className="truncate font-semibold">{t('platformAdminShell.title')}</span>
                  <span className="truncate text-xs text-muted-foreground">{t('platformAdminShell.subtitle')}</span>
                </div>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarHeader>

        <SidebarContent>
          <nav aria-label={t('shell.mainNavigation')} className="flex-1 space-y-0.5 overflow-y-auto py-3 px-3 group-data-[collapsible=icon]:px-1.5">
            {navigation.map((item) => (
              <SidebarNavItem key={item.label} item={item} onNavigate={onNavigate} collapsed={sidebarCollapsed} />
            ))}
          </nav>

          <Separator />

          <nav aria-label={t('shell.secondaryNavigation')} className="space-y-0.5 py-2 px-3 group-data-[collapsible=icon]:px-1.5">
            {bottomNav.map((item) => (
              <SidebarNavItem key={item.label} item={item} onNavigate={onNavigate} collapsed={sidebarCollapsed} />
            ))}
          </nav>
        </SidebarContent>

        <SidebarFooter>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                className={cn(
                  'flex items-center rounded-lg text-sm hover:bg-accent transition-colors h-auto',
                  sidebarCollapsed ? 'justify-center w-full' : 'gap-3 w-full items-center px-2 py-2',
                )}
              >
                <Avatar className="h-8 w-8 flex-shrink-0">
                  {profile.avatarUrl && <AvatarImage src={profile.avatarUrl} alt={profile.firstName} />}
                  <AvatarFallback className="bg-primary text-primary-foreground text-xs">
                    {profile.avatarInitials}
                  </AvatarFallback>
                </Avatar>
                {!sidebarCollapsed && (
                  <>
                    <div className="flex-1 text-left min-w-0">
                      <p className="text-sm font-medium leading-none truncate">
                        {profile.lastName} {profile.firstName[0]}.
                      </p>
                      <div className="flex items-center gap-1 mt-0.5">
                        <Badge variant="outline" className="text-xs px-1 py-0 h-4">
                          {t('roles.ADMIN')}
                        </Badge>
                      </div>
                    </div>
                    <ChevronUp className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                  </>
                )}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align={sidebarCollapsed ? 'end' : 'start'} className="w-64" side="top">
              <div className="px-2 py-2">
                <p className="text-sm font-medium">{profile.lastName} {profile.firstName}</p>
                <p className="text-xs text-muted-foreground">{profile.email}</p>
                <Badge variant="secondary" className="text-xs mt-1.5">{t('roles.ADMIN')}</Badge>
              </div>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => onNavigate('profile')}>
                <User className="mr-2 h-4 w-4" />
                {t('shell.profile')}
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => onNavigate('settings')}>
                <Settings className="mr-2 h-4 w-4" />
                {t('shell.settings')}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className="text-destructive"
                onClick={async () => {
                  await useAuthStore.getState().logout();
                  window.location.href = '/';
                }}
              >
                <LogOut className="mr-2 h-4 w-4" />
                {t('shell.logout')}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </SidebarFooter>

        <SidebarRail />
      </Sidebar>

      <SidebarInset>
        <header className="flex h-14 items-center justify-between border-b bg-background px-4 md:px-6">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <SidebarTrigger className="-ml-1" />
            <Separator orientation="vertical" className="mr-2 h-4" />
            <ShieldCheck className="h-4 w-4 text-primary" />
            <span className="hidden sm:inline">{t('platformAdminShell.title')}</span>
          </div>
          <div className="flex items-center gap-2">
            <CommandPaletteTrigger onOpen={() => setPaletteOpen(true)} />
            <NotificationCenter />
          </div>
        </header>
        <main className="flex-1 overflow-y-auto p-6">{children}</main>
      </SidebarInset>
      <CommandPalette
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
        onNavigate={onNavigate}
      />
      <AdminShortcuts onNavigate={onNavigate} onOpenPalette={() => setPaletteOpen(true)} />
    </TooltipProvider>
  );
}

export default PlatformAdminShell;
