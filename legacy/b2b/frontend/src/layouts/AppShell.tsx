import { useState } from 'react';
import {
  LayoutDashboard,
  Package,
  ShoppingCart,
  FileText,
  Settings,
  HelpCircle,
  Bell,
  MessageSquare,
  ChevronDown,
  Search,
  BarChart3,
  Plug,
  Factory,
  Layers,
  ClipboardList,
  Users,
  User,
  LogOut,
  ChevronUp,
  Store,
  Truck,
  Calculator,
  Handshake,
  Check,
  PanelLeftClose,
  PanelLeftOpen,
  Minus,
  Plus,
  X,
  Menu,
  CheckCircle2,
  UserPlus,
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
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
  SheetFooter,
} from '@/components/ui/sheet';
import { ScrollArea } from '@/components/ui/scroll-area';

import { useTranslation } from 'react-i18next';
import {
  useUserStore,
  type CompanyStatus,
  type UserRole,
} from '@/store/userStore';
import { useCartStore, useCartCount } from '@/store/cartStore';
import { useCurrencyStore } from '@/store/currencyStore';
import { useDemoStore } from '@/store/demoStore';

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
    { label: t('shell.myRequests'), icon: <ClipboardList className="h-4 w-4" />, id: 'my-requests', active: activePage === 'my-requests', badge: 3 },
    { label: t('shell.commercialOffers'), icon: <Calculator className="h-4 w-4" />, id: 'crm-quotes', active: activePage === 'crm-quotes', badge: 2 },
    { label: t('shell.documents'), icon: <FileText className="h-4 w-4" />, id: 'my-documents', active: activePage === 'my-documents' },
    { label: t('shell.purchaseTemplates'), icon: <ClipboardList className="h-4 w-4" />, id: 'purchase-templates', active: activePage === 'purchase-templates' },
    { label: t('shell.logistics'), icon: <Truck className="h-4 w-4" />, id: 'logistics', active: activePage === 'logistics' },
  ];
  if (role === 'ADMIN' || role === 'MANAGER') {
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
    {
      label: t('shell.productionOrders'), icon: <Factory className="h-4 w-4" />,
      children: [
        { label: t('shell.incomingOrders'), id: 'production-orders', active: activePage === 'production-orders' },
        { label: t('shell.productionSchedule'), id: 'production-schedule', active: activePage === 'production-schedule' },
      ],
    },
    { label: t('shell.quotes'), icon: <Calculator className="h-4 w-4" />, id: 'crm-quotes', active: activePage === 'crm-quotes', badge: 4 },
    { label: t('shell.documents'), icon: <FileText className="h-4 w-4" />, id: 'my-documents', active: activePage === 'my-documents' },
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
      label: t('shell.crm'), icon: <Handshake className="h-4 w-4" />, badge: 8,
      children: [
        { label: t('shell.deals'), id: 'crm-deals', active: activePage === 'crm-deals' },
        { label: t('shell.quotes'), id: 'crm-quotes', active: activePage === 'crm-quotes' },
        { label: t('shell.clients'), id: 'crm-clients', active: activePage === 'crm-clients' },
      ],
    },
    { label: t('shell.logistics'), icon: <Truck className="h-4 w-4" />, id: 'logistics', active: activePage === 'logistics' },
    { label: t('shell.documents'), icon: <FileText className="h-4 w-4" />, id: 'my-documents', active: activePage === 'my-documents' },
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
    items.push({ label: t('shell.integrations'), icon: <Plug className="h-4 w-4" />, id: 'integrations' });
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

function statusColor(_status: CompanyStatus): string {
  return 'text-primary';
}

/* ─── Sidebar nav item component ────────────────────────────────────── */

function SidebarNavItem({
  item,
  onNavigate,
  collapsed,
}: {
  item: NavItem;
  onNavigate: (id: string) => void;
  collapsed: boolean;
}) {
  const hasActiveChild = item.children?.some((c) => c.active) ?? false;
  const [open, setOpen] = useState(hasActiveChild);

  if (item.children) {
    return (
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger asChild>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                className={cn(
                  'flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors hover:bg-accent hover:text-accent-foreground',
                  hasActiveChild ? 'text-foreground' : 'text-muted-foreground',
                  collapsed && 'justify-center px-0'
                )}
              >
                {item.icon}
                {!collapsed && (
                  <>
                    <span className="flex-1 text-left">{item.label}</span>
                    {item.badge != null && (
                      <Badge className="h-5 min-w-5 justify-center rounded-full px-1.5 text-xs">
                        {item.badge}
                      </Badge>
                    )}
                    <ChevronDown className={cn('h-4 w-4 transition-transform', open && 'rotate-180')} />
                  </>
                )}
              </button>
            </TooltipTrigger>
            {collapsed && <TooltipContent side="right">{item.label}</TooltipContent>}
          </Tooltip>
        </CollapsibleTrigger>
        {!collapsed && (
          <CollapsibleContent>
            <div className="ml-4 mt-1 flex flex-col gap-0.5 border-l pl-3">
              {item.children.map((child) => (
                <button
                  key={child.id}
                  className={cn(
                    'rounded-md px-3 py-1.5 text-left text-sm transition-colors hover:bg-accent hover:text-accent-foreground',
                    child.active ? 'bg-accent font-medium text-foreground' : 'text-muted-foreground'
                  )}
                  onClick={() => onNavigate(child.id)}
                >
                  {child.label}
                </button>
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
        <button
          className={cn(
            'flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors hover:bg-accent hover:text-accent-foreground',
            item.active ? 'bg-accent text-foreground' : 'text-muted-foreground',
            collapsed && 'justify-center px-0'
          )}
          onClick={() => item.id && onNavigate(item.id)}
        >
          {item.icon}
          {!collapsed && (
            <>
              <span>{item.label}</span>
              {item.badge != null && (
                <Badge className="ml-auto h-5 min-w-5 justify-center rounded-full px-1.5 text-xs">
                  {item.badge}
                </Badge>
              )}
            </>
          )}
        </button>
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

export function AppShell({ children, activePage, onNavigate, onStartTour }: AppShellProps) {
  const { t } = useTranslation();
  const { role, activeStatus, profile, company, setActiveStatus } = useUserStore();
  const { items: cartItems, clearCart } = useCartStore();
  const cartCount = useCartCount();
  const { currency, setCurrency } = useCurrencyStore();
  const { isDemoMode, toggleDemoMode } = useDemoStore();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [cartSheetOpen, setCartSheetOpen] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [notificationCount, setNotificationCount] = useState(3);

  const navigation = getNavigation(activeStatus, activePage, role, t);
  const bottomNav = getBottomNavigation(role, t);

  const handleSubmitCart = () => {
    clearCart();
    setCartSheetOpen(false);
    onNavigate('my-requests');
  };

  return (
    <TooltipProvider>
      <div className="flex h-screen overflow-hidden bg-muted/30">
        {/* Sidebar — hidden on mobile, collapsible on desktop */}
        <aside className={cn(
          'hidden md:flex flex-col border-r bg-background transition-all duration-200',
          sidebarCollapsed ? 'w-16' : 'w-64'
        )}>
          {/* Company branding — top */}
          <div className={cn(
            'flex h-14 items-center border-b',
            sidebarCollapsed ? 'justify-center px-2' : 'gap-2 px-4'
          )}>
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground flex-shrink-0">
              <Layers className="h-4 w-4" />
            </div>
            {!sidebarCollapsed && (
              <div className="flex-1 min-w-0">
                <span className="text-sm font-bold tracking-tight leading-none truncate block">{company.name || 'RAILTECH'}</span>
                <p className="text-xs text-muted-foreground truncate">{t('shell.b2bPlatform')}</p>
              </div>
            )}
          </div>

          {/* Company status switcher */}
          {!sidebarCollapsed && company.statusEntries.filter(e => e.verification === 'verified').length > 1 && (
            <div className="px-3 pt-3">
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button className="flex w-full items-center gap-2 rounded-lg border bg-muted/50 px-3 py-2 text-sm hover:bg-accent transition-colors">
                    <StatusIcon status={activeStatus} className={cn('h-4 w-4', statusColor(activeStatus))} />
                    <span className="flex-1 text-left font-medium">
                      {t(`companyStatus.${activeStatus}`)}
                    </span>
                    <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                  </button>
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
          {!sidebarCollapsed && (
            <div className="px-3 pt-3">
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input placeholder={`${t('common.search')}...`} className="h-8 pl-8 text-xs" />
              </div>
            </div>
          )}

          {/* Main navigation */}
          <nav className={cn(
            'flex-1 space-y-0.5 overflow-y-auto py-3 transition-all duration-200',
            sidebarCollapsed ? 'px-1.5' : 'px-3'
          )}>
            {navigation.map((item) => (
              <SidebarNavItem key={item.label} item={item} onNavigate={onNavigate} collapsed={sidebarCollapsed} />
            ))}
          </nav>

          <Separator />

          {/* Bottom navigation */}
          <nav className={cn(
            'space-y-0.5 py-2 transition-all duration-200',
            sidebarCollapsed ? 'px-1.5' : 'px-3'
          )}>
            {bottomNav.map((item) => (
              <SidebarNavItem key={item.label} item={item} onNavigate={onNavigate} collapsed={sidebarCollapsed} />
            ))}
          </nav>

          <Separator />

          {/* Sidebar collapse button */}
          <div className={cn(
            'px-1.5 py-2 transition-all duration-200',
            sidebarCollapsed ? '' : 'px-3'
          )}>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="w-full justify-center"
                  onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
                >
                  {sidebarCollapsed ? (
                    <PanelLeftOpen className="h-4 w-4" />
                  ) : (
                    <PanelLeftClose className="h-4 w-4" />
                  )}
                </Button>
              </TooltipTrigger>
              {sidebarCollapsed && <TooltipContent side="right">{t('catalog.sidebar.expand')}</TooltipContent>}
            </Tooltip>
          </div>

          {/* User info — bottom */}
          <div className={cn(
            'transition-all duration-200',
            sidebarCollapsed ? 'p-1.5' : 'p-3'
          )}>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button className={cn(
                  'flex items-center rounded-lg text-sm hover:bg-accent transition-colors',
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
                </button>
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
                <DropdownMenuItem onClick={toggleDemoMode}>
                  <span className={cn('mr-2 h-2 w-2 rounded-full', isDemoMode ? 'bg-primary' : 'bg-muted-foreground/30')} />
                  {t('shell.demoMode')}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem className="text-destructive">
                  <LogOut className="mr-2 h-4 w-4" />
                  {t('shell.logout')}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </aside>

        {/* Main */}
        <div className="flex flex-1 flex-col overflow-hidden">
          <header className="flex h-14 items-center justify-between border-b bg-background px-4 md:px-6">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              {/* Mobile hamburger */}
              <Button
                variant="ghost"
                size="icon"
                className="md:hidden"
                aria-label={t('shell.openMenu')}
                onClick={() => setMobileNavOpen(true)}
              >
                <Menu className="h-5 w-5" />
              </Button>
              <StatusIcon status={activeStatus} className={cn('h-4 w-4 hidden sm:block', statusColor(activeStatus))} />
              <span className="hidden sm:inline">{t(`companyStatus.${activeStatus}`)}</span>
              <span className="hidden sm:inline text-muted-foreground/50">/</span>
              <span className="truncate">{company.name}</span>
            </div>
            <div className="flex items-center gap-2">
              {/* Currency toggle */}
              <div className="flex items-center rounded-lg border p-0.5 gap-0.5">
                <Button
                  variant={currency === 'USD' ? 'default' : 'ghost'}
                  size="sm"
                  className="h-7 px-2.5 text-xs"
                  onClick={() => setCurrency('USD')}
                >
                  USD
                </Button>
                <Button
                  variant={currency === 'UZS' ? 'default' : 'ghost'}
                  size="sm"
                  className="h-7 px-2.5 text-xs"
                  onClick={() => setCurrency('UZS')}
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
                  <Button variant="ghost" size="icon" className="relative" aria-label={t('cart.title')} onClick={() => setCartSheetOpen(true)}>
                    <ShoppingCart className="h-4 w-4" />
                    {cartCount > 0 && (
                      <span className="absolute -right-0 -top-0 flex h-4 w-4 items-center justify-center rounded-full bg-primary text-xs font-medium text-primary-foreground">
                        {cartCount}
                      </span>
                    )}
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t('cart.title')}</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="ghost" size="icon" className="relative" aria-label={t('chat.title')} onClick={() => setChatOpen(true)}>
                    <MessageSquare className="h-4 w-4" />
                    <span className="absolute -right-0 -top-0 flex h-4 w-4 items-center justify-center rounded-full bg-primary text-xs font-medium text-primary-foreground">
                      2
                    </span>
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t('chat.title')}</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="ghost" size="icon" className="relative" aria-label={t('notifications.title')} onClick={() => { setNotificationsOpen(true); setNotificationCount(0); }}>
                    <Bell className="h-4 w-4" />
                    {notificationCount > 0 && (
                      <span className="absolute -right-0 -top-0 flex h-4 w-4 items-center justify-center rounded-full bg-destructive text-xs font-medium text-destructive-foreground">
                        {notificationCount}
                      </span>
                    )}
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t('notifications.title')}</TooltipContent>
              </Tooltip>
            </div>
          </header>
          <main className="flex-1 overflow-y-auto p-6">{children}</main>
        </div>

        {/* Notifications Sheet */}
        <Sheet open={notificationsOpen} onOpenChange={setNotificationsOpen}>
          <SheetContent side="right" className="w-full sm:w-96 flex flex-col">
            <SheetHeader>
              <SheetTitle>Уведомления</SheetTitle>
              <SheetDescription>Последние события в системе</SheetDescription>
            </SheetHeader>
            <ScrollArea className="flex-1 -mx-6 px-6">
              <div className="space-y-2 pr-4">
                {[
                  { title: 'КП-2026-003 отправлено', desc: 'Коммерческое предложение для UTY отправлено на рассмотрение', time: '5 мин назад', type: 'success' as const, icon: CheckCircle2, iconBg: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400' },
                  { title: 'Новая заявка ЗК-2026-0052', desc: 'Получена заявка от Tashkent Metro на 8 позиций', time: '1 час назад', type: 'info' as const, icon: FileText, iconBg: 'bg-primary/10 text-primary' },
                  { title: 'Заявка ЗК-2026-0047 обработана', desc: 'Smart Match нашёл 6 из 8 позиций в каталоге', time: '3 часа назад', type: 'info' as const, icon: Package, iconBg: 'bg-primary/10 text-primary' },
                  { title: 'Новый пользователь', desc: 'Иванов А.С. присоединился к команде как Менеджер', time: 'Вчера', type: 'default' as const, icon: UserPlus, iconBg: 'bg-muted text-muted-foreground' },
                  { title: 'Обновление системы', desc: 'Версия 2.4.1 — улучшен Quote Builder', time: '2 дня назад', type: 'default' as const, icon: Settings, iconBg: 'bg-muted text-muted-foreground' },
                ].map((n, i) => {
                  const isUnread = i < 3;
                  return (
                    <div key={i} className={cn(
                      'rounded-lg border p-3 cursor-pointer hover:bg-muted/50 transition-colors',
                      isUnread && 'border-l-2 border-l-primary bg-accent/50',
                    )}>
                      <div className="flex gap-3">
                        <div className={cn('flex h-9 w-9 shrink-0 items-center justify-center rounded-full', n.iconBg)}>
                          <n.icon className="h-4 w-4" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-start justify-between gap-2">
                            <p className="text-sm font-semibold leading-tight">{n.title}</p>
                            <span className="shrink-0 text-xs text-muted-foreground whitespace-nowrap">{n.time}</span>
                          </div>
                          <p className="text-xs text-muted-foreground mt-1 leading-relaxed">{n.desc}</p>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </ScrollArea>
            <SheetFooter>
              <Button variant="outline" className="w-full" onClick={() => setNotificationsOpen(false)}>
                Отметить все как прочитанные
              </Button>
            </SheetFooter>
          </SheetContent>
        </Sheet>

        {/* Chat Sheet */}
        <Sheet open={chatOpen} onOpenChange={setChatOpen}>
          <SheetContent side="right" className="w-full sm:w-96 flex flex-col">
            <SheetHeader>
              <SheetTitle>Сообщения</SheetTitle>
              <SheetDescription>Переписка с контрагентами</SheetDescription>
            </SheetHeader>
            <ScrollArea className="flex-1 -mx-6 px-6">
              <div className="space-y-3 pr-4">
                {[
                  { name: 'Алексей Петров', company: 'SAUT Plant', message: 'Уточните пожалуйста количество по тележке 18-100...', time: '10 мин', unread: true },
                  { name: 'Мария Сидорова', company: 'UTY Tashkent', message: 'Готовы принять КП, ждём обновлённый расчёт', time: '45 мин', unread: true },
                  { name: 'Дмитрий Ким', company: 'RATEP Ekb', message: 'Отгрузка планируется на следующей неделе', time: '2 часа', unread: false },
                  { name: 'Фаррух Исмоилов', company: 'Navoi Mining', message: 'Спасибо, документы получили', time: 'Вчера', unread: false },
                ].map((chat, i) => (
                  <div key={i} className={cn(
                    'rounded-lg border p-3 cursor-pointer hover:bg-muted/50 transition-colors',
                    chat.unread && 'bg-accent border-accent'
                  )}>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Avatar className="h-8 w-8">
                          <AvatarFallback className="bg-muted text-xs">
                            {chat.name.split(' ').map(w => w[0]).join('')}
                          </AvatarFallback>
                        </Avatar>
                        <div>
                          <p className="text-sm font-medium">{chat.name}</p>
                          <p className="text-xs text-muted-foreground">{chat.company}</p>
                        </div>
                      </div>
                      <span className="text-xs text-muted-foreground">{chat.time}</span>
                    </div>
                    <p className="text-xs text-muted-foreground mt-2 line-clamp-2">{chat.message}</p>
                    {chat.unread && (
                      <Badge className="mt-2 text-xs">{t('common.new', 'New')}</Badge>
                    )}
                  </div>
                ))}
              </div>
            </ScrollArea>
            <SheetFooter>
              <Button className="w-full">Открыть все сообщения</Button>
            </SheetFooter>
          </SheetContent>
        </Sheet>

        {/* Cart Sheet */}
        <Sheet open={cartSheetOpen} onOpenChange={setCartSheetOpen}>
          <SheetContent side="right" className="w-full sm:w-96 flex flex-col">
            <SheetHeader>
              <SheetTitle>Запрос на закупку</SheetTitle>
              <SheetDescription>
                {cartCount} {cartCount === 1 ? 'позиция' : 'позиций'} в запросе
              </SheetDescription>
            </SheetHeader>

            {cartItems.length === 0 ? (
              <div className="flex flex-1 items-center justify-center">
                <div className="text-center">
                  <ShoppingCart className="mx-auto h-12 w-12 text-muted-foreground mb-2" />
                  <p className="text-sm text-muted-foreground">Запрос на закупку пуст</p>
                </div>
              </div>
            ) : (
              <ScrollArea className="flex-1 -mx-6 px-6">
                <div className="space-y-3 pr-4">
                  {cartItems.map((cartItem) => (
                    <div key={cartItem.product.id} className="flex items-start gap-3 rounded-lg border p-3">
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate">{cartItem.product.name}</p>
                        <p className="text-xs text-muted-foreground mt-0.5">{cartItem.product.uom || 'шт'}</p>
                      </div>
                      <div className="flex items-center gap-1 flex-shrink-0">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7"
                          onClick={() => useCartStore.setState(state => ({
                            items: state.items.map(i =>
                              i.product.id === cartItem.product.id
                                ? { ...i, quantity: Math.max(1, i.quantity - 1) }
                                : i
                            ).filter(i => i.quantity > 0)
                          }))}
                        >
                          <Minus className="h-3 w-3" />
                        </Button>
                        <span className="w-7 text-center text-xs font-medium">{cartItem.quantity}</span>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7"
                          onClick={() => useCartStore.setState(state => ({
                            items: state.items.map(i =>
                              i.product.id === cartItem.product.id
                                ? { ...i, quantity: i.quantity + 1 }
                                : i
                            )
                          }))}
                        >
                          <Plus className="h-3 w-3" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 ml-1"
                          onClick={() => useCartStore.getState().removeItem(cartItem.product.id)}
                        >
                          <X className="h-3 w-3" />
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              </ScrollArea>
            )}

            <SheetFooter className="flex-col gap-2 sm:flex-col">
              <Button
                variant="outline"
                className="w-full"
                onClick={() => {
                  clearCart();
                  setCartSheetOpen(false);
                }}
              >
                Очистить
              </Button>
              <Button
                className="w-full"
                onClick={handleSubmitCart}
                disabled={cartItems.length === 0}
              >
                Отправить запрос
              </Button>
            </SheetFooter>
          </SheetContent>
        </Sheet>

        {/* Mobile Navigation Sheet */}
        <Sheet open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
          <SheetContent side="left" className="w-72 p-0 flex flex-col">
            <SheetHeader className="p-4 border-b">
              <div className="flex items-center gap-2">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                  <Layers className="h-4 w-4" />
                </div>
                <SheetTitle className="text-sm font-bold">{company.name || 'RAILTECH'}</SheetTitle>
              </div>
              <SheetDescription className="sr-only">{t('shell.b2bPlatform')}</SheetDescription>
            </SheetHeader>
            <ScrollArea className="flex-1">
              <nav className="space-y-0.5 p-3">
                {navigation.map((item) => (
                  <div key={item.label}>
                    {item.children ? (
                      <div className="space-y-0.5">
                        <p className="px-3 py-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                          {item.label}
                        </p>
                        {item.children.map((child) => (
                          <button
                            key={child.id}
                            className={cn(
                              'flex w-full items-center rounded-lg px-3 py-2 text-sm transition-colors hover:bg-accent',
                              child.active ? 'bg-accent font-medium text-foreground' : 'text-muted-foreground'
                            )}
                            onClick={() => { onNavigate(child.id); setMobileNavOpen(false); }}
                          >
                            {child.label}
                          </button>
                        ))}
                      </div>
                    ) : (
                      <button
                        className={cn(
                          'flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors hover:bg-accent',
                          item.active ? 'bg-accent font-medium text-foreground' : 'text-muted-foreground'
                        )}
                        onClick={() => { item.id && onNavigate(item.id); setMobileNavOpen(false); }}
                      >
                        {item.icon}
                        <span>{item.label}</span>
                        {item.badge != null && (
                          <Badge className="ml-auto h-5 min-w-5 justify-center rounded-full px-1.5 text-xs">
                            {item.badge}
                          </Badge>
                        )}
                      </button>
                    )}
                  </div>
                ))}
              </nav>
              <Separator />
              <nav className="space-y-0.5 p-3">
                {bottomNav.map((item) => (
                  <button
                    key={item.label}
                    className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent"
                    onClick={() => { item.id && onNavigate(item.id); setMobileNavOpen(false); }}
                  >
                    {item.icon}
                    <span>{item.label}</span>
                  </button>
                ))}
              </nav>
            </ScrollArea>
          </SheetContent>
        </Sheet>
      </div>
    </TooltipProvider>
  );
}
