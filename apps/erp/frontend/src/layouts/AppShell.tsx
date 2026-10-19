import { useState, useMemo } from 'react';
import {
  Settings,
  ChevronDown,
  Layers,
  User,
  LogOut,
  ChevronUp,
  Search,
  Coins,
  Compass,
  ExternalLink,
} from 'lucide-react';
import { toast } from 'sonner';
import { issueSsoToken } from '@/api/ssoApi';

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
import { buildNavigation, TENANT_NAV, TENANT_BOTTOM_NAV } from '@/config/navigation';
import { useCurrencyStore } from '@/store/currencyStore';
import { useAuthStore } from '@/store/authStore';
import { NotificationCenter } from '@/components/Layout/NotificationCenter';
import { DocumentSearchDialog } from '@/components/Layout/DocumentSearchDialog';
import { useCommandPaletteShortcut, useCommandPaletteState } from '@/components/Layout/useCommandPalette';
import { canSwitchToCrm } from './crmSwitch';
import { sidebarDefaultOpen } from './sidebarDefaultOpen';
import { roleDisplayName } from '@/components/Settings/team/roleErrors';

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
    // Radix `asChild` must chain to a single DOM element. Tooltip between
    // CollapsibleTrigger and <Button> breaks the handler forwarding, making
    // the collapsible header unclickable. Tooltip → Collapsible → Button fixes
    // it.
    return (
      <Tooltip>
        <Collapsible open={disabled ? false : open} onOpenChange={disabled ? undefined : setOpen}>
          <TooltipTrigger asChild>
            <CollapsibleTrigger asChild>
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
            </CollapsibleTrigger>
          </TooltipTrigger>
          {collapsed && <TooltipContent side="right">{item.label}</TooltipContent>}
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
      </Tooltip>
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
  /**
   * Full-bleed content mode: drops the `p-6` padding and the page-scroll
   * so a workspace page (e.g. the КП builder) can own the whole content viewport and
   * manage its own single scroll. Default false — every other page keeps the standard chrome.
   */
  fullBleed?: boolean;
}

export function AppShell(props: AppShellProps) {
  return (
    // U2 (root cause of «видно 3 строки»): shadcn's sidebar wrapper is `flex min-h-svh` — a MIN
    // height, which is NOT a definite height. Every `flex-1 min-h-0` below it therefore resolved
    // against CONTENT, so the КП builder's scroll container (`flex-1 overflow-auto` in GridTable)
    // grew to fit all 61 lines (clientHeight === scrollHeight, `scrollable: false`) instead of
    // clipping: the whole PAGE scrolled, the sticky header/totals had nothing to stick inside, and
    // @tanstack/react-virtual — which windows by that element's scroll — never engaged at all in the
    // default view (it only worked in fullscreen, whose `fixed inset-0` supplies its own definite
    // height). `h-svh` gives the wrapper that definite height, so the existing min-h-0 chain finally
    // resolves. Scoped to fullBleed workspace pages, so the standard `overflow-y-auto p-6` page
    // scroll everywhere else is untouched.
    // На планшете сайдбар стартует свёрнутым в иконки — иначе его 256px режут таблицы
    // (см. `sidebarDefaultOpen`).
    <SidebarProvider className={props.fullBleed ? 'h-svh' : undefined} defaultOpen={sidebarDefaultOpen()}>
      <AppShellInner {...props} />
    </SidebarProvider>
  );
}

function AppShellInner({ children, activePage, onNavigate, onStartTour, fullBleed = false }: AppShellProps) {
  const { t } = useTranslation();
  const { profile, company, capabilities } = useUserStore();
  // Подпись роли в шапке — роли бэк-офиса (M1-ERP-05), а не должность приглашения; администратор
  // (is_superuser) без ролей — «Администратор».
  const isSuperuser = useAuthStore((st) => st.user?.is_superuser === true);
  const roleNames = (capabilities.roles ?? []).map((role) => roleDisplayName(role, t));
  const roleLabel = roleNames.length > 0
    ? roleNames.join(', ')
    : isSuperuser ? t('team.rolesSection.administrator') : null;
  const { currency, setCurrency, rateIsFallback } = useCurrencyStore();
  const { state } = useSidebar();
  const sidebarCollapsed = state === 'collapsed';
  // E2: Header flex shrinking — left container (min-w-0) allows company name truncation,
  // right container (flex-shrink-0) protects action icons from clipping at 1366px.
  // ADR-0005: ONE config-driven nav, filtered by the role's permissions. Реестры видны всем
  // сотрудникам (просмотр открыт), пункты-инструменты без права СКРЫТЫ (M1-ERP-05).
  const navigation = useMemo(
    () => buildNavigation(TENANT_NAV, capabilities, activePage, t),
    [capabilities, activePage, t],
  );
  const bottomNav = useMemo(
    () => buildNavigation(TENANT_BOTTOM_NAV, capabilities, activePage, t),
    [capabilities, activePage, t],
  );

  // Global document search (Cmd/Ctrl+K). Documents carry a ready-to-use deep-link `hash`, so the dialog assigns
  // `window.location.hash` directly (App.tsx handleNavigate only accepts clean page ids).
  const [searchOpen, setSearchOpen] = useCommandPaletteState();
  useCommandPaletteShortcut(() => setSearchOpen(true));

  const [ssoLoading, setSsoLoading] = useState(false);

  const handleGoToCrm = async () => {
    setSsoLoading(true);
    try {
      const data = await issueSsoToken();
      window.location.href = `${data.redirect_url}#token=${data.token}`;
    } catch {
      toast.error(t('sso.goToCrmFailed'));
    } finally {
      setSsoLoading(false);
    }
  };

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
                  <span className="truncate font-semibold">{company.name || t('nav.myCompany')}</span>
                  <span className="truncate text-xs text-muted-foreground">
                    {company.inn ? `${t('nav.inn')} ${company.inn}` : t('shell.b2bPlatform')}
                  </span>
                </div>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarHeader>

        <SidebarContent>
          {/* Main navigation */}
          <nav aria-label={t('shell.mainNavigation')} className="flex-1 space-y-0.5 overflow-y-auto py-3 px-3 group-data-[collapsible=icon]:px-1.5">
            {navigation.map((item) => (
              <SidebarNavItem key={item.label} item={item} onNavigate={onNavigate} collapsed={sidebarCollapsed} />
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
                    {profile.avatarUrl && <AvatarImage src={profile.avatarUrl} alt={profile.firstName} />}
                    <AvatarFallback className="bg-primary text-primary-foreground text-xs">
                      {profile.avatarInitials}
                    </AvatarFallback>
                  </Avatar>
                  {!sidebarCollapsed && (
                    <>
                      <div className="flex-1 text-left min-w-0">
                        <p className="text-sm font-medium leading-none truncate">
                          {profile.firstName ? `${profile.lastName} ${profile.firstName[0]}.` : profile.email}
                        </p>
                        {roleLabel && (
                          <div className="flex items-center gap-1 mt-0.5 min-w-0">
                            <Badge variant="outline" className="text-xs px-1 py-0 h-4 max-w-full truncate">
                              {roleLabel}
                            </Badge>
                          </div>
                        )}
                      </div>
                      <ChevronUp className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                    </>
                  )}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align={sidebarCollapsed ? 'end' : 'start'} className="w-64" side="top">
                <div className="px-2 py-2">
                  <p className="text-sm font-medium">
                    {profile.firstName
                      ? `${profile.lastName} ${profile.firstName} ${profile.patronymic}`.trim()
                      : profile.email}
                  </p>
                  <p className="text-xs text-muted-foreground">{profile.email}</p>
                  {(roleNames.length > 0 || isSuperuser) && (
                    <div className="flex flex-wrap items-center gap-1.5 mt-1.5">
                      {roleNames.length > 0 ? (
                        roleNames.map((name) => (
                          <Badge key={name} variant="secondary" className="text-xs">
                            {name}
                          </Badge>
                        ))
                      ) : (
                        <Badge variant="secondary" className="text-xs">
                          {t('team.rolesSection.administrator')}
                        </Badge>
                      )}
                    </div>
                  )}
                </div>

                {/* Мобильный дубль вторичных действий шапки: на узком экране правый кластер
                    занимал 459px при вьюпорте 375px и толкал страницу. Эталон (Gmail, Odoo):
                    вторичное уезжает в меню, а не пропадает. На sm+ эти пункты скрыты — там
                    работают исходные контролы в шапке. */}
                <DropdownMenuSeparator className="sm:hidden" />
                <DropdownMenuItem
                  className="sm:hidden"
                  onSelect={(event) => {
                    event.preventDefault();
                    setCurrency(currency === 'UZS' ? 'USD' : 'UZS');
                  }}
                >
                  <Coins className="mr-2 h-4 w-4" />
                  {t('shell.currencySelector')}
                  <span className="ml-auto text-xs font-medium tabular-nums">{currency}</span>
                </DropdownMenuItem>
                {onStartTour && (
                  <DropdownMenuItem className="sm:hidden" onClick={onStartTour}>
                    <Compass className="mr-2 h-4 w-4" />
                    {t('shell.startTour')}
                  </DropdownMenuItem>
                )}
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
                <DropdownMenuItem className="text-destructive" onClick={async () => {
                  await useAuthStore.getState().logout();
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
            <div className="flex items-center gap-2 text-sm text-muted-foreground min-w-0">
              <SidebarTrigger className="-ml-1" />
              <Separator orientation="vertical" className="mr-2 h-4" />
              <span className="truncate">{company.name}</span>
            </div>
            <div className="flex items-center gap-2 flex-shrink-0">
              {/* Currency toggle */}
              {/* На узком экране валюта и тур уезжают в меню «ещё» — правый кластер занимал 459px
                  при вьюпорте 375px и толкал страницу (проход глазами 03-08). Эталон: Gmail и
                  Odoo оставляют на мобильном 1–2 ключевых действия, остальное под «⋮». */}
              <div className="hidden sm:flex items-center rounded-lg border p-0.5 gap-0.5" role="radiogroup" aria-label={t('shell.currencySelector')}>
                <Button
                  variant={currency === 'USD' ? 'default' : 'ghost'}
                  size="sm"
                  className="h-7 px-2.5 text-xs"
                  onClick={() => setCurrency('USD')}
                  role="radio"
                  aria-checked={currency === 'USD'}
                  // Курс с сервера не приехал: пересчёт идёт по резервному, и суммы в USD
                  // приблизительны. Молча выдавать их за настоящие нельзя (аудит UI, U2).
                  title={rateIsFallback ? t('shell.fxRateFallback') : undefined}
                >
                  USD
                  {rateIsFallback ? <span aria-hidden="true">*</span> : null}
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

              {/* Tour button — launches the onboarding walkthrough. Hidden for users
                  who already completed it or dismissed the prompt. */}
              {onStartTour && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button variant="outline" size="sm" className="hidden sm:inline-flex text-xs gap-1.5 h-8" onClick={onStartTour}>
                      {t('shell.startTour')}
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>{t('shell.startTourTooltip')}</TooltipContent>
                </Tooltip>
              )}

              <Separator orientation="vertical" className="h-6" />
              {/* Global document search — icon-only on small screens, labelled + ⌘K hint above sm */}
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 gap-2 text-muted-foreground"
                    onClick={() => setSearchOpen(true)}
                    aria-label={t('search.trigger')}
                  >
                    <Search className="h-4 w-4" />
                    <span className="hidden md:inline text-xs">{t('search.trigger')}</span>
                    <kbd className="pointer-events-none hidden items-center gap-1 rounded border bg-muted px-1.5 py-0.5 font-mono text-xs font-medium md:inline-flex">
                      <span className="text-xs">⌘</span>K
                    </kbd>
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t('search.trigger')}</TooltipContent>
              </Tooltip>

              {/* Переход в CRM через SSO (CONTRACTS §6) — SSO включён (FIX-03) и сотрудник провиженен из CRM (FIX-11). */}
              {canSwitchToCrm(capabilities) && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-8 gap-1.5 text-xs font-medium"
                      disabled={ssoLoading}
                      onClick={handleGoToCrm}
                      aria-label={t('sso.goToCrm')}
                    >
                      <ExternalLink className="h-3.5 w-3.5" />
                      <span className="hidden sm:inline">{t('sso.goToCrm')}</span>
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>{t('sso.goToCrmTooltip')}</TooltipContent>
                </Tooltip>
              )}

              <NotificationCenter onNavigate={onNavigate} />

            </div>
          </header>
          <DocumentSearchDialog
            open={searchOpen}
            onOpenChange={setSearchOpen}
            onNavigate={(hash) => { window.location.hash = hash; }}
          />
          <main className={cn('flex-1 min-h-0', fullBleed ? 'overflow-hidden' : 'overflow-y-auto p-6')}>
            {children}
          </main>
      </SidebarInset>



    </TooltipProvider>
  );
}
