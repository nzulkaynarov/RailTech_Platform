import React from 'react';
import { Outlet, Link, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Train, ShoppingCart, LogOut, User, Settings, ExternalLink } from 'lucide-react';
import { useAuthStore } from '@/store/authStore';
import { useCartStore } from '@/store/cartStore';
import { CartDrawer } from '@/components/ui/CartDrawer';
import { TopLoadingBar } from '@/components/ui/TopLoadingBar';
import { NotificationCenter } from '@/components/Layout/NotificationCenter';
import { LanguageSwitcher } from '@/components/ui/LanguageSwitcher';
import { ThemeToggle } from '@/components/ui/ThemeToggle';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import {
    DropdownMenu,
    DropdownMenuTrigger,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu';
import { Avatar, AvatarImage, AvatarFallback } from '@/components/ui/avatar';
import { cn } from '@/lib/utils';

const AccountMenu: React.FC = () => {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const { user, isAuthenticated, logout } = useAuthStore();

    if (!isAuthenticated) {
        return (
            <div className="flex items-center gap-2">
                <Button variant="ghost" size="sm" asChild>
                    <Link to="/">{t('auth.login')}</Link>
                </Button>
                <Button size="sm" asChild>
                    <Link to="/">{t('auth.login')}</Link>
                </Button>
            </div>
        );
    }

    const initials = user?.first_name
        ? user.first_name[0].toUpperCase()
        : (user?.email?.[0] ?? 'U').toUpperCase();

    const handleLogout = () => {
        logout();
        navigate('/');
    };

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <Button variant="outline" size="sm" className="gap-2">
                    <Avatar size="sm">
                        {user?.profile_picture ? (
                            <AvatarImage src={user.profile_picture} alt={user.first_name ?? ''} />
                        ) : null}
                        <AvatarFallback>{initials}</AvatarFallback>
                    </Avatar>
                    <span className="hidden sm:block max-w-[120px] truncate">
                        {user?.first_name ?? user?.email}
                    </span>
                </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuLabel className="flex flex-col gap-0.5">
                    <span className="truncate">{user?.first_name ?? user?.email}</span>
                    <span className="text-xs font-normal text-muted-foreground truncate">
                        {user?.email}
                    </span>
                    {user?.company?.name && (
                        <span className="text-xs font-normal text-muted-foreground truncate">
                            {user.company.name}
                        </span>
                    )}
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuGroup>
                    <DropdownMenuItem onSelect={() => navigate('/cabinet/home')}>
                        <User />
                        {t('nav.cabinet')}
                    </DropdownMenuItem>
                    <DropdownMenuItem onSelect={() => navigate('/cabinet/profile')}>
                        <Settings />
                        {t('nav.profile')}
                    </DropdownMenuItem>
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuItem variant="destructive" onSelect={handleLogout}>
                    <LogOut />
                    {t('nav.logout')}
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    );
};

export const CatalogShell: React.FC = () => {
    const { t } = useTranslation();
    const { toggleCart, items } = useCartStore();
    const { isAuthenticated } = useAuthStore();
    const cartCount = items.reduce((sum, i) => sum + i.quantity, 0);

    return (
        <div className="flex flex-col h-screen bg-background overflow-hidden">
            <TopLoadingBar />

            {/* Header */}
            <header className="h-14 border-b bg-background flex items-center px-4 lg:px-6 gap-4 shrink-0 z-30">
                {/* Logo */}
                <Link
                    to="/catalog"
                    className={cn(
                        'flex items-center gap-2.5 mr-2 shrink-0 rounded-lg',
                        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'
                    )}
                    aria-label="RailTech B2B"
                >
                    <div className="w-8 h-8 bg-primary rounded-lg flex items-center justify-center shrink-0">
                        <Train className="w-5 h-5 text-primary-foreground" aria-hidden="true" />
                    </div>
                    <div>
                        <span className="text-base font-bold text-foreground tracking-tight">
                            Rail<span className="text-primary">Tech</span>
                        </span>
                        <span className="text-xs text-muted-foreground ml-1.5 hidden sm:inline">
                            B2B
                        </span>
                    </div>
                </Link>

                {/* Nav links */}
                <nav className="hidden md:flex items-center gap-1">
                    <Button variant="secondary" size="sm" asChild>
                        <Link to="/catalog">{t('nav.catalog')}</Link>
                    </Button>
                    <Button variant="ghost" size="sm" asChild>
                        <a href="#" target="_blank" rel="noopener noreferrer">
                            {t('nav.corporateSite')}
                            <ExternalLink className="size-3" aria-hidden="true" />
                        </a>
                    </Button>
                </nav>

                {/* Right side */}
                <div className="ml-auto flex items-center gap-2">
                    <LanguageSwitcher />
                    <ThemeToggle />

                    <Separator orientation="vertical" className="h-6" />

                    {/* Notifications (only when authenticated) */}
                    {isAuthenticated && <NotificationCenter />}

                    {/* Cart */}
                    <Button
                        variant="outline"
                        size="icon-sm"
                        onClick={toggleCart}
                        aria-label={t('cart.title')}
                        className="relative"
                    >
                        <ShoppingCart className="size-4" aria-hidden="true" />
                        {cartCount > 0 && (
                            <Badge className="absolute -top-1.5 -right-1.5 h-4 min-w-4 px-1 text-xs">
                                {cartCount > 9 ? '9+' : cartCount}
                            </Badge>
                        )}
                    </Button>

                    <Separator orientation="vertical" className="h-6" />

                    {/* Account */}
                    <AccountMenu />
                </div>
            </header>

            {/* Page content */}
            <main className="flex-1 overflow-hidden min-h-0">
                <Outlet />
            </main>

            {/* Footer separator + footer */}
            <Separator />
            <footer className="h-9 bg-background flex items-center justify-between px-4 lg:px-6 shrink-0">
                <p className="text-xs text-muted-foreground">
                    &copy; {new Date().getFullYear()} {t('nav.companyName', { defaultValue: 'ООО «RailTech»' })}
                </p>
                <Button variant="link" size="sm" className="text-xs text-muted-foreground h-auto p-0" asChild>
                    <a href="#" target="_blank" rel="noopener noreferrer">
                        {t('nav.corporateSite')}
                        <ExternalLink className="size-3" aria-hidden="true" />
                    </a>
                </Button>
            </footer>

            {/* Global drawers */}
            <CartDrawer />
        </div>
    );
};
