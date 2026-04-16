import { useState, useMemo } from 'react';
import {
  LayoutDashboard,
  Package,
  ShoppingCart,
  Settings,
  HelpCircle,
  ChevronDown,
  Search,
  BarChart3,
  Factory,
  Layers,
  ClipboardList,
  Users,
  User,
  LogOut,
  ChevronUp,
  Store,
  Calculator,
  Handshake,
  Check,
  ShieldCheck,
  CreditCard,
} from 'lucide-react';

import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
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
  DropdownMenuLabel,
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
import {
  useUserStore,
  type CompanyStatus,
  type UserRole,
} from '@/store/userStore';
import { useCartStore, useCartCount } from '@/store/cartStore';
import { useCurrencyStore } from '@/store/currencyStore';
import { useAuthStore } from '@/store/authStore';
import { NotificationCenter } from '@/components/Layout/NotificationCenter';
import { ChatDrawer } from '@/components/Layout/ChatDrawer';
import { CartDrawer } from '@/components/ui/CartDrawer';

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

/* ─── Status-based navigation (what the user sees depends on context) ─ */

type TFn = (key: string) => string;

function getBuyerNavigation(activePage: string, role: UserRole, t: TFn): NavItem[] {
  const items: NavItem[] = [
    { label: t('shell.dashboard'), icon: <LayoutDashboard className="h-4 w-4" />, id: 'dashboard', active: activePage === 'dashboard' },
    { label: t('shell.catalog'), icon: <Package className="h-4 w-4" />, id: 'products', active: activePage === 'products' },
    { label: t('shell.myRequests'), icon: <ClipboardList className="h-4 w-4" />, id: 'my-requests', active: activePage === 'my-requests' },
    { label: t('shell.commercialOffers'), icon: <Calculator className="h-4 w-4" />, id: 'crm-quotes', active: activePage === 'crm-quotes' },
  ];
  if (role === 'ADMIN' || role === 'MANAGER') {
    items.push({ label: t('shell.deals'), icon: <Handshake className="h-4 w-4" />, id: 'crm-deals', active: activePage === 'crm-deals' });
    items.push({ label: t('shell.clients'), icon: <Users className="h-4 w-4" />, id: 'crm-clients', active: activePage === 'crm-clients' });
    items.push({ label: t('shell.analytics'), icon: <BarChart3 className="h-4 w-4" />, id: 'analytics', active: activePage === 'analytics' });
  }
  return items;
}

function getManufacturerNavigation(activePage: string, role: UserRole, t: TFn): NavItem[] {
  const items: NavItem[] = [
    { label: t('shell.dashboard'), icon: <LayoutDashboard className="h-4 w-4" />, id: 'dashboard', active: activePage === 'dashboard' },
    {
      label: t('shell.nomenclature'), icon: <Package className="h-4 w-4" />,
      children: [
        { label: t('shell.products'), id: 'products', active: activePage === 'products' },
        { label: t('shell.categories'), id: 'categories', active: activePage === 'categories' },
        { label: t('shell.equipmentGroups'), id: 'equipment-groups', active: activePage === 'equipment-groups' },
      ],
    },
    { label: t('shell.deals'), icon: <Handshake className="h-4 w-4" />, id: 'crm-deals', active: activePage === 'crm-deals' },
    { label: t('shell.quotes'), icon: <Calculator className="h-4 w-4" />, id: 'crm-quotes', active: activePage === 'crm-quotes' },
  ];
  if (role === 'ADMIN' || role === 'MANAGER') {
    items.push({ label: t('shell.productionAnalytics'), icon: <BarChart3 className="h-4 w-4" />, id: 'analytics', active: activePage === 'analytics' });
  }
  return items;
}

function getSellerNavigation(activePage: string, role: UserRole, t: TFn): NavItem[] {
  const items: NavItem[] = [
    { label: t('shell.dashboard'), icon: <LayoutDashboard className="h-4 w-4" />, id: 'dashboard', active: activePage === 'dashboard' },
    {
      label: t('shell.catalog'), icon: <Package className="h-4 w-4" />,
      children: [
        { label: t('shell.nomenclature'), id: 'products', active: activePage === 'products' },
        { label: t('shell.categories'), id: 'categories', active: activePage === 'categories' },
        { label: t('shell.equipmentGroups'), id: 'equipment-groups', active: activePage === 'equipment-groups' },
      ],
    },
    {
      label: t('shell.sourcing'), icon: <ShoppingCart className="h-4 w-4" />,
      children: [
        { label: t('shell.requests'), id: 'sourcing-requests', active: activePage === 'sourcing-requests' },
        { label: t('shell.excelImport'), id: 'sourcing-import', active: activePage === 'sourcing-import' },
        { label: t('shell.smartMatch'), id: 'sourcing-match', active: activePage === 'sourcing-match' },
      ],
    },
    {
      label: t('shell.crm'), icon: <Handshake className="h-4 w-4" />,
      children: [
        { label: t('shell.deals'), id: 'crm-deals', active: activePage === 'crm-deals' },
        { label: t('shell.quotes'), id: 'crm-quotes', active: activePage === 'crm-quotes' },
        { label: t('shell.clients'), id: 'crm-clients', active: activePage === 'crm-clients' },
      ],
    },
  ];
  if (role === 'ADMIN' || role === 'MANAGER') {
    items.push({ label: t('shell.salesAnalytics'), icon: <BarChart3 className="h-4 w-4" />, id: 'analytics', active: activePage === 'analytics' });
  }
  return items;
}

function getNavigation(status: CompanyStatus, activePage: string, role: UserRole, t: TFn): NavItem[] {
  switch (status) {
    case 'BUYER': return getBuyerNavigation(activePage, role, t);
    case 'MANUFACTURER': return getManufacturerNavigation(activePage, role, t);
    case 'SELLER': return getSellerNavigation(activePage, role, t);
    default: return getSellerNavigation(activePage, role, t);
  }
}

function getBottomNavigation(role: UserRole, t: TFn): NavItem[] {
  const items: NavItem[] = [
    { label: t('shell.settings'), icon: <Settings className="h-4 w-4" />, id: 'settings' },
  ];
  if (role === 'ADMIN') {
    items.push({ label: t('shell.users'), icon: <Users className="h-4 w-4" />, id: 'admin-users' });
    items.push({ label: t('shell.kyc'), icon: <ShieldCheck className="h-4 w-4" />, id: 'admin-kyc' });
    items.push({ label: t('shell.subscriptions'), icon: <CreditCard className="h-4 w-4" />, id: 'admin-subscriptions' });
    items.push({ label: t('shell.roleApplications'), icon: <ClipboardList className="h-4 w-4" />, id: 'admin-role-apps' });
  }
  items.push({ label: t('shell.help'), icon: <HelpCircle className="h-4 w-4" />, id: 'help' });
  return items;
}

/* ─── Status icon helper ────────────────────────────────────────────── */

function StatusIcon({ status, className }: { status: CompanyStatus; className?: string }) {
  switch (status) {
    case 'BUYER':
      return <ShoppingCart className={className} />;
    case 'MANUFACTURER':
      return <Factory className={className} />;
    case 'SELLER':
      return <Store className={className} />;
  }
}

/* ─── Status color helper ───────────────────────────────────────────── */

// eslint-disable-next-line @typescript-eslint/no-unused-vars
function statusColor(_status: CompanyStatus): string {
  return 'text-primary';
}

/* ─── Sidebar nav item component ────────────────────────────────────── */

function SidebarNavItem({
  item,
  onNavigate,
  collapsed,
  disabled = false,
}: {
  item: NavItem;
  disabled?: boolean;
  onNavigate: (id: string) => void;
  collapsed: boolean;
}) {
  const hasActiveChild = item.children?.some((c) => c.active) ?? false;
  const [open, setOpen] = useState(hasActiveChild);

  if (item.children) {
    return (
      <Collapsible open={disabled ? false : open} onOpenChange={disabled ? undefined : setOpen}>
        <CollapsibleTrigger asChild>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                disabled={disabled}
                className={cn(
                  'flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors h-auto',
                  disabled ? 'opacity-40 cursor-not-allowed' : 'hover:bg-accent hover:text-accent-foreground',
                  hasActiveChild ? 'text-foreground' : 'text-muted-foreground',
                  collapsed && 'justify-center px-0'
                )}
              >
                {item.icon}
                {!collapsed && (
                  <>
                    <span className="flex-1 text-left truncate">{item.label}</span>
                    {item.badge != null && (
                      <Badge className="h-5 min-w-5 justify-center rounded-full px-1.5 text-xs">
                        {item.badge}
                      </Badge>
                    )}
                    {!disabled && <ChevronDown className={cn('h-4 w-4 transition-transform', open && 'rotate-180')} aria-hidden="true" />}
                  </>
                )}
              </Button>
            </TooltipTrigger>
            {collapsed && <TooltipContent side="right">{item.label}</TooltipContent>}
          </Tooltip>
        </CollapsibleTrigger>
        {!collapsed && !disabled && (
          <CollapsibleContent>
            <div className="ml-4 mt-1 flex flex-col gap-0.5 border-l pl-3">
              {item.children.map((child) => (
                <Button
                  key={child.id}
                  variant="ghost"
                  className={cn(
                    'rounded-md px-3 py-1.5 text-left text-sm transition-colors hover:bg-accent hover:text-accent-foreground h-auto w-full justify-start',
                    child.active ? 'bg-accent font-medium text-foreground' : 'text-muted-foreground'
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
    );
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          disabled={disabled}
          className={cn(
            'flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors h-auto',
            disabled ? 'opacity-40 cursor-not-allowed' : 'hover:bg-accent hover:text-accent-foreground',
            item.active ? 'bg-accent text-foreground' : 'text-muted-foreground',
            collapsed && 'justify-center px-0'
          )}
          onClick={() => !disabled && item.id && onNavigate(item.id)}
        >
          {item.icon}
          {!collapsed && (
            <>
              <span className="flex-1 text-left truncate">{item.label}</span>
              {item.badge != null && (
                <Badge className="ml-auto h-5 min-w-5 justify-center rounded-full px-1.5 text-xs">
                  {item.badge}
                </Badge>
              )}
            </>
          )}
        </Button>
      </TooltipTrigger>
      {collapsed && <TooltipContent side="right">{item.label}</TooltipContent>}
    </Tooltip>
  );
}

/* ─── AppShell ──────────────────────────────────────────────────────── */

interface AppShellProps {
  children: React.ReactNode;
  activePage: string;
  onNavigate: (target: string) => void;
  onStartTour?: () => void;
}

export function AppShell(props: AppShellProps) {
  return (
    <SidebarProvider>
      <AppShellInner {...props} />
    </SidebarProvider>
  );
}

function AppShellInner({ children, activePage, onNavigate, onStartTour }: AppShellProps) {
  const { t } = useTranslation();
  const { role, activeStatus, profile, company, setActiveStatus } = useUserStore();
  const cartCount = useCartCount();
  const { currency, setCurrency } = useCurrencyStore();
  const { state } = useSidebar();
  const sidebarCollapsed = state === 'collapsed';
  const isKycVerified = company.kycStatus === 'verified';
  const navigation = useMemo(() => getNavigation(activeStatus, activePage, role, t), [activeStatus, activePage, role, t]);
  const bottomNav = useMemo(() => getBottomNavigation(role, t), [role, t]);


  return (
      <TooltipProvider>
      <Sidebar collapsible="icon">
        <SidebarHeader>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton size="lg" onClick={() => onNavigate('dashboard')}>
                <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                  <Layers className="size-4" />
                </div>
                <div className="grid flex-1 text-left text-sm leading-tight">
                  <span className="truncate font-semibold">{company.name || t('nav.companyName')}</span>
                  <span className="truncate text-xs text-muted-foreground">{t('shell.b2bPlatform')}</span>
                </div>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarHeader>

        <SidebarContent>
          {/* Company status switcher */}
          {company.statusEntries.filter(e => e.verification === 'verified').length > 1 && (
            <div className="px-3 pt-3 group-data-[collapsible=icon]:hidden">
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" className="flex w-full items-center gap-2 rounded-lg border bg-muted/50 px-3 py-2 text-sm hover:bg-accent transition-colors h-auto">
                    <StatusIcon status={activeStatus} className={cn('h-4 w-4', statusColor(activeStatus))} />
                    <span className="flex-1 text-left font-medium">
                      {t(`companyStatus.${activeStatus}`)}
                    </span>
                    <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" className="w-56">
                  <DropdownMenuLabel className="text-xs text-muted-foreground font-normal">
                    {t('shell.workContext')}
                  </DropdownMenuLabel>
                  {company.statusEntries.filter(e => e.verification === 'verified').map((entry) => (
                    <DropdownMenuItem
                      key={entry.status}
                      className={cn('gap-3', activeStatus === entry.status && 'bg-accent')}
                      onClick={() => {
                        setActiveStatus(entry.status);
                        onNavigate('dashboard');
                      }}
                    >
                      <StatusIcon status={entry.status} className={cn('h-4 w-4', statusColor(entry.status))} />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium">{t(`companyStatus.${entry.status}`)}</p>
                        <p className="text-xs text-muted-foreground truncate">{t(`companyStatusDesc.${entry.status}`)}</p>
                      </div>
                      {activeStatus === entry.status && <Check className="h-4 w-4 text-primary" />}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          )}

          {/* Search */}
          <div className="px-3 pt-3 group-data-[collapsible=icon]:hidden">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
              <Input placeholder={`${t('common.search')}...`} className="h-8 pl-8 text-xs" aria-label={t('common.search')} />
            </div>
          </div>

          {/* Main navigation */}
          <nav aria-label={t('shell.mainNavigation')} className="flex-1 space-y-0.5 overflow-y-auto py-3 px-3 group-data-[collapsible=icon]:px-1.5">
            {navigation.map((item) => (
              <SidebarNavItem key={item.label} item={item} onNavigate={onNavigate} collapsed={sidebarCollapsed} disabled={!isKycVerified} />
            ))}
          </nav>

          <Separator />

          {/* Bottom navigation */}
          <nav aria-label={t('shell.secondaryNavigation')} className="space-y-0.5 py-2 px-3 group-data-[collapsible=icon]:px-1.5">
            {bottomNav.map((item) => (
              <SidebarNavItem key={item.label} item={item} onNavigate={onNavigate} collapsed={sidebarCollapsed} />
            ))}
          </nav>
        </SidebarContent>

        <SidebarFooter>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" className={cn(
                  'flex items-center rounded-lg text-sm hover:bg-accent transition-colors h-auto',
                  sidebarCollapsed ? 'justify-center w-full' : 'gap-3 w-full items-center px-2 py-2'
                )}>
                  <Avatar className="h-8 w-8 flex-shrink-0">
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
                            {t(`roles.${role}`)}
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
                  <p className="text-sm font-medium">
                    {profile.lastName} {profile.firstName} {profile.patronymic}
                  </p>
                  <p className="text-xs text-muted-foreground">{profile.email}</p>
                  <div className="flex items-center gap-1.5 mt-1.5">
                    <Badge variant="secondary" className="text-xs">
                      {t(`roles.${role}`)}
                    </Badge>
                    <Badge variant="outline" className={cn('text-xs', statusColor(activeStatus))}>
                      {t(`companyStatus.${activeStatus}`)}
                    </Badge>
                  </div>
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
                <DropdownMenuItem className="text-destructive" onClick={() => {
                  useAuthStore.getState().logout();
                  window.location.href = '/';
                }}>
                  <LogOut className="mr-2 h-4 w-4" />
                  {t('shell.logout')}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
        </SidebarFooter>

        <SidebarRail />
      </Sidebar>

      <SidebarInset>
        {/* Main */}
          <header className="flex h-14 items-center justify-between border-b bg-background px-4 md:px-6">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <SidebarTrigger className="-ml-1" />
              <Separator orientation="vertical" className="mr-2 h-4" />
              <StatusIcon status={activeStatus} className={cn('h-4 w-4 hidden sm:block', statusColor(activeStatus))} />
              <span className="hidden sm:inline">{t(`companyStatus.${activeStatus}`)}</span>
              <span className="hidden sm:inline text-muted-foreground/50">/</span>
              <span className="truncate">{company.name}</span>
            </div>
            <div className="flex items-center gap-2">
              {/* Currency toggle */}
              <div className="flex items-center rounded-lg border p-0.5 gap-0.5" role="radiogroup" aria-label={t('shell.currencySelector')}>
                <Button
                  variant={currency === 'USD' ? 'default' : 'ghost'}
                  size="sm"
                  className="h-7 px-2.5 text-xs"
                  onClick={() => setCurrency('USD')}
                  role="radio"
                  aria-checked={currency === 'USD'}
                >
                  USD
                </Button>
                <Button
                  variant={currency === 'UZS' ? 'default' : 'ghost'}
                  size="sm"
                  className="h-7 px-2.5 text-xs"
                  onClick={() => setCurrency('UZS')}
                  role="radio"
                  aria-checked={currency === 'UZS'}
                >
                  UZS
                </Button>
              </div>

              {/* Tour button */}
              {onStartTour && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button variant="outline" size="sm" className="text-xs gap-1.5 h-8" onClick={onStartTour}>
                      {t('shell.demoMode')}
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>{t('shell.demoMode')}</TooltipContent>
                </Tooltip>
              )}

              <Separator orientation="vertical" className="h-6" />
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="ghost" size="icon" className="relative" aria-label={t('cart.title')} onClick={() => useCartStore.getState().openCart()}>
                    <ShoppingCart className="h-4 w-4" />
                    {cartCount > 0 && (
                      <Badge className="absolute -top-1 -right-1 size-4 p-0 text-xs font-bold">
                        {cartCount}
                      </Badge>
                    )}
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t('cart.title')}</TooltipContent>
              </Tooltip>
              <CartDrawer />
              <ChatDrawer onNavigate={onNavigate} />
              <NotificationCenter />
            </div>
          </header>
          <main className="flex-1 overflow-y-auto p-6">{children}</main>
      </SidebarInset>



    </TooltipProvider>
  );
}
