import React, { useState } from 'react';
import { Outlet, Link, useLocation } from 'react-router-dom';
import {
    LayoutDashboard,
    Search,
    LogOut,
    Bell,
    Menu,
    Train,
    ChevronRight,
    ShieldCheck,
    Settings,
    Database
} from 'lucide-react';
import { clsx } from 'clsx';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

interface NavItemProps {
    to: string;
    icon: React.ElementType;
    label: string;
    active: boolean;
    onClick?: () => void;
    count?: number;
}

const NavItem: React.FC<NavItemProps> = ({ to, icon: Icon, label, active, onClick, count }) => (
    <Link
        to={to}
        onClick={onClick}
        className={clsx(
            "flex items-center justify-between h-8 px-2 rounded-sm transition-colors mb-[2px] group",
            active
                ? "bg-primary text-primary-foreground"
                : "text-sidebar-foreground/60 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
        )}
    >
        <div className="flex items-center gap-2">
            <Icon className={clsx("w-3.5 h-3.5", active ? "text-primary-foreground" : "text-sidebar-foreground/50 group-hover:text-sidebar-foreground/80")} />
            <span className="text-xs font-medium tracking-tight">{label}</span>
        </div>
        {count ? (
            <span className={clsx("text-xs px-1 rounded-sm font-bold", active ? "bg-primary-foreground/20 text-primary-foreground" : "bg-sidebar-accent text-sidebar-foreground/50")}>
                {count}
            </span>
        ) : (
            active && <ChevronRight className="w-3 h-3 opacity-50" />
        )}
    </Link>
);

export const AppShell: React.FC = () => {
    const location = useLocation();
    const [, setIsMobileMenuOpen] = useState(false);
    const { t } = useTranslation();

    const commerceNav = [
        { to: '/dashboard', icon: LayoutDashboard, label: t('shell.nav.crmDeals'), count: 12 },
        { to: '/catalog', icon: Search, label: t('shell.nav.catalog') },
    ];

    const adminNav = [
        { to: '/admin/sourcing', icon: Database, label: t('shell.nav.smartMatch') },
        { to: '/admin/kyc', icon: ShieldCheck, label: t('shell.nav.kycManager') },
        { to: '/admin', icon: Settings, label: t('shell.nav.systemControl') },
    ];

    return (
        <div className="flex h-screen bg-sidebar text-foreground overflow-hidden font-sans antialiased">
            {/* Sidebar - Industrial Compact (200px) */}
            <aside className="hidden lg:flex w-48 flex-col bg-sidebar border-r border-sidebar-border h-full shrink-0">
                <div className="h-10 flex items-center px-4 bg-muted/40 border-b border-sidebar-border shrink-0">
                    <div className="flex items-center gap-2">
                        <div className="w-5 h-5 bg-primary rounded-sm flex items-center justify-center">
                            <Train className="w-3.5 h-3.5 text-primary-foreground" />
                        </div>
                        <span className="text-sidebar-foreground font-black tracking-tighter text-xs uppercase">RailTech <span className="text-primary">B2B</span></span>
                    </div>
                </div>

                <nav className="flex-1 overflow-y-auto py-4 custom-scrollbar">
                    <div className="px-4 mb-6">
                        <p className="text-xs font-bold text-sidebar-foreground/40 uppercase tracking-widest mb-1 px-1">{t('shell.sections.commerce')}</p>
                        {commerceNav.map((item) => (
                            <NavItem
                                key={item.to}
                                {...item}
                                active={location.pathname === item.to}
                            />
                        ))}
                    </div>

                    <div className="px-4">
                        <p className="text-xs font-bold text-sidebar-foreground/40 uppercase tracking-widest mb-1 px-1">{t('shell.sections.infrastructure')}</p>
                        {adminNav.map((item) => (
                            <NavItem
                                key={item.to}
                                {...item}
                                active={location.pathname === item.to}
                            />
                        ))}
                    </div>
                </nav>

                <div className="p-4 border-t border-sidebar-border bg-muted/20">
                    <div className="flex items-center gap-2 mb-4">
                        <div className="w-7 h-7 rounded-sm bg-sidebar-accent flex items-center justify-center text-xs font-bold text-sidebar-foreground/60 border border-sidebar-border">
                            AD
                        </div>
                        <div className="min-w-0">
                            <p className="text-xs font-bold text-sidebar-foreground truncate">admin@railtech.uz</p>
                            <p className="text-xs text-sidebar-foreground/50 uppercase font-black tracking-tighter">{t('shell.systemAdmin')}</p>
                        </div>
                    </div>
                    <Button variant="ghost" size="sm" className="w-full justify-start gap-2 h-7 px-2 text-sidebar-foreground/50 hover:bg-sidebar-accent hover:text-destructive font-bold text-xs uppercase">
                        <LogOut className="w-3 h-3" />
                        {t('shell.signOut')}
                    </Button>
                </div>
            </aside>

            {/* Content Matrix */}
            <div className="flex-1 flex flex-col min-w-0 bg-background">
                {/* Compact Navbar (40px) */}
                <header className="h-10 bg-card border-b border-border px-4 flex items-center justify-between shrink-0 z-50">
                    <div className="flex items-center gap-6">
                        <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => setIsMobileMenuOpen(true)}
                            className="lg:hidden h-7 w-7 text-muted-foreground"
                        >
                            <Menu size={18} />
                        </Button>

                        <div className="hidden sm:flex items-center gap-4 text-xs text-muted-foreground uppercase font-bold tracking-tight">
                            <span>{t('shell.breadcrumb.main')}</span>
                            <ChevronRight size={10} className="text-muted-foreground/60" />
                            <span className="text-foreground">{location.pathname.split('/').pop() || 'Dashboard'}</span>
                        </div>
                    </div>

                    <div className="flex items-center gap-4">
                        <div className="relative group hidden md:block">
                            <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3 h-3 text-muted-foreground" />
                            <Input
                                type="text"
                                placeholder={t('shell.globalSearch')}
                                className="w-48 h-6 bg-muted border-none text-xs pl-8 rounded-sm"
                            />
                        </div>

                        <div className="h-4 w-px bg-border mx-1"></div>

                        <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-primary relative">
                            <Bell size={14} />
                            <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 bg-destructive rounded-full"></span>
                        </Button>
                    </div>
                </header>

                {/* Data Viewport */}
                <main className="flex-1 overflow-hidden relative">
                    <div className="w-full h-full p-4 custom-scrollbar overflow-auto">
                        <Outlet />
                    </div>
                </main>
            </div>
        </div>
    );
};
