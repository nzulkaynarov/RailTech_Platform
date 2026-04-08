import React from 'react';
import { useTranslation } from 'react-i18next';
import { Database, ShieldCheck, Activity, UserPlus, Upload, FileText, Package, Users, Box, Target } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useUsers } from '../../hooks/useAccounts';
import { useProducts } from '../../hooks/useCatalog';
import { useAnalytics, useActivityLogs } from '../../hooks/useCRM';
import { KPICard } from '@/components/ui/KPICard';
import { EmptyState } from '@/components/ui/EmptyState';
import { Skeleton } from '@/components/ui/LoadingSkeleton';

export const AdminDashboard: React.FC = () => {
    const { t } = useTranslation();
    const { data: users = [], isLoading: usersLoading } = useUsers();
    const { data: products = [], isLoading: productsLoading } = useProducts();
    const { data: analytics, isLoading: analyticsLoading } = useAnalytics();
    const { data: activityLogs = [], isLoading: logsLoading } = useActivityLogs();

    const loading = usersLoading || productsLoading || analyticsLoading || logsLoading;

    return (
        <div className="p-4 lg:p-6 h-full space-y-5">
            {/* Header */}
            <div className="flex items-end justify-between border-b border-border pb-3">
                <div>
                    <h1 className="text-xl font-bold tracking-tight text-foreground">
                        {t('admin.dashboard.title')}
                    </h1>
                    <p className="text-sm text-muted-foreground mt-0.5">{t('admin.dashboard.systemHealth')}</p>
                </div>
                <div className="flex items-center gap-1.5 px-2 py-1 bg-success/10 border border-success/20 rounded-lg text-success text-xs font-medium">
                    <Activity className="w-3 h-3" aria-hidden="true" />
                    {t('chat.connected')}
                </div>
            </div>

            {/* KPI Grid */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                <KPICard
                    icon={<FileText className="w-4 h-4 text-primary" />}
                    label={t('dashboard.kpi.activePipeline')}
                    value={loading ? '...' : analytics?.total_pipeline_value ? `${analytics.total_pipeline_value.toLocaleString()} $` : '0 $'}
                    isLoading={loading}
                    href="/crm/analytics"
                />
                <KPICard
                    icon={<Database className="w-4 h-4 text-amber-500" />}
                    label={t('sourcing.title')}
                    value={loading ? '...' : analytics?.sourcing_backlog ?? 0}
                    isLoading={loading}
                    href="/crm/sourcing"
                />
                <KPICard
                    icon={<Activity className="w-4 h-4 text-success" />}
                    label={t('dashboard.kpi.closedDeals')}
                    value={loading ? '...' : analytics ? `${analytics.mapped_items_percentage || 0}%` : '0%'}
                    isLoading={loading}
                    href="/crm/analytics"
                />
                <KPICard
                    icon={<ShieldCheck className="w-4 h-4 text-primary" />}
                    label={t('admin.dashboard.totalProducts')}
                    value={loading ? '...' : products.length}
                    isLoading={loading}
                    href="/admin/nomenclature"
                />
            </div>

            {/* Stats row */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                {[
                    { label: t('admin.dashboard.totalProducts'), value: products.length, icon: Package, color: 'text-[var(--color-chart-1)]', bg: 'bg-[var(--color-chart-1)]/10' },
                    { label: t('admin.dashboard.totalUsers'), value: users.length, icon: Users, color: 'text-[var(--color-chart-2)]', bg: 'bg-[var(--color-chart-2)]/10' },
                    { label: t('sourcing.title'), value: analytics?.sourcing_backlog || 0, icon: Box, color: 'text-[var(--color-chart-3)]', bg: 'bg-[var(--color-chart-3)]/10' },
                    { label: t('dashboard.kpi.closedDeals'), value: `${analytics?.mapped_items_percentage || 0}%`, icon: Target, color: 'text-[var(--color-chart-4)]', bg: 'bg-[var(--color-chart-4)]/10' },
                ].map((stat, i) => (
                    <div key={i} className="bg-card border border-border p-3 rounded-lg shadow-sm flex items-center gap-4 group hover:border-primary/30 transition-all">
                        <div className={`w-10 h-10 ${stat.bg} rounded-lg flex items-center justify-center ${stat.color} border border-black/5`}>
                            <stat.icon className="w-5 h-5" aria-hidden="true" />
                        </div>
                        <div>
                            <div className="text-lg font-bold text-foreground tracking-tight leading-none mb-0.5">
                                {loading ? <Skeleton className="h-5 w-12" /> : stat.value}
                            </div>
                            <div className="text-xs text-muted-foreground">{stat.label}</div>
                        </div>
                    </div>
                ))}
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                {/* Quick Access */}
                <div className="lg:col-span-2">
                    <div className="bg-card border border-border rounded-xl p-5 shadow-sm">
                        <h2 className="text-sm font-bold text-foreground mb-4 pb-2 border-b border-border flex items-center gap-2">
                            <Activity className="w-3.5 h-3.5 text-muted-foreground" aria-hidden="true" />
                            {t('admin.dashboard.quickAccess')}
                        </h2>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                            <Link to="/admin/users" className="flex items-center gap-4 p-4 rounded-lg border border-border hover:border-primary/30 hover:bg-muted transition-colors group focus-ring">
                                <div className="w-10 h-10 rounded-lg bg-muted flex items-center justify-center text-muted-foreground border border-border">
                                    <UserPlus className="w-5 h-5" aria-hidden="true" />
                                </div>
                                <div>
                                    <div className="text-sm font-semibold text-foreground">{t('admin.users.title')}</div>
                                    <div className="text-xs text-muted-foreground mt-0.5">{t('admin.users.role')}</div>
                                </div>
                            </Link>

                            <Link to="/admin/nomenclature" className="flex items-center gap-4 p-4 rounded-lg border border-border hover:border-primary/30 hover:bg-muted transition-colors group focus-ring">
                                <div className="w-10 h-10 rounded-lg bg-muted flex items-center justify-center text-muted-foreground border border-border">
                                    <Upload className="w-5 h-5" aria-hidden="true" />
                                </div>
                                <div>
                                    <div className="text-sm font-semibold text-foreground">{t('admin.nomenclature.title')}</div>
                                    <div className="text-xs text-muted-foreground mt-0.5">{t('admin.nomenclature.importExcel')}</div>
                                </div>
                            </Link>

                            <Link to="/admin/settings" className="flex items-center gap-4 p-4 rounded-lg border border-border hover:border-primary/30 hover:bg-muted transition-colors group focus-ring">
                                <div className="w-10 h-10 rounded-lg bg-muted flex items-center justify-center text-muted-foreground border border-border">
                                    <Activity className="w-5 h-5" aria-hidden="true" />
                                </div>
                                <div>
                                    <div className="text-sm font-semibold text-foreground">{t('nav.settings')}</div>
                                    <div className="text-xs text-muted-foreground mt-0.5">{t('admin.dashboard.recentActivity')}</div>
                                </div>
                            </Link>

                            <div className="flex items-center justify-center p-4 rounded-lg border border-border border-dashed bg-muted/30">
                                <span className="text-xs text-muted-foreground text-center">{t('common.noData')}</span>
                            </div>
                        </div>
                    </div>
                </div>

                {/* Event Feed */}
                <div className="lg:col-span-1">
                    <div className="bg-card border border-border rounded-xl p-5 shadow-sm h-full flex flex-col">
                        <div className="flex items-center justify-between mb-4 pb-2 border-b border-border">
                            <h2 className="text-sm font-bold text-foreground">{t('admin.dashboard.recentActivity')}</h2>
                            <Link to="/crm/analytics" className="text-xs font-semibold text-primary hover:text-primary/80 transition-colors focus-ring rounded">
                                {t('admin.dashboard.viewAllLogs')}
                            </Link>
                        </div>

                        <div className="flex-1 space-y-4 relative overflow-y-auto custom-scrollbar pr-1">
                            {logsLoading ? (
                                <div className="space-y-3">
                                    {Array.from({ length: 4 }).map((_, i) => (
                                        <div key={i} className="flex gap-3">
                                            <Skeleton className="w-7 h-7 rounded-lg shrink-0" />
                                            <div className="flex-1 space-y-1.5">
                                                <Skeleton className="h-3 w-3/4" />
                                                <Skeleton className="h-2.5 w-full" />
                                                <Skeleton className="h-2 w-20" />
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            ) : activityLogs.length === 0 ? (
                                <EmptyState
                                    title={t('notifications.empty')}
                                    className="py-8"
                                />
                            ) : (
                                activityLogs.slice(0, 10).map((event) => {
                                    const levelConfig: Record<string, { color: string; bg: string; icon: React.ElementType }> = {
                                        INFO: { color: 'text-primary', bg: 'bg-primary/10', icon: Activity },
                                        SUCCESS: { color: 'text-success', bg: 'bg-success/10', icon: ShieldCheck },
                                        WARNING: { color: 'text-warning', bg: 'bg-warning/10', icon: Activity },
                                        ERROR: { color: 'text-destructive', bg: 'bg-destructive/10', icon: Activity },
                                    };
                                    const conf = levelConfig[event.level] || levelConfig.INFO;

                                    return (
                                        <div key={event.id} className="flex gap-3 group">
                                            <div className="shrink-0 mt-0.5">
                                                <div className={`w-7 h-7 rounded-lg flex items-center justify-center ${conf.bg} ${conf.color} border border-border`}>
                                                    <conf.icon className="w-3.5 h-3.5" aria-hidden="true" />
                                                </div>
                                            </div>
                                            <div className="min-w-0">
                                                <div className="text-sm font-semibold text-foreground truncate">{event.action}</div>
                                                <div className="text-xs text-muted-foreground mb-0.5 leading-normal line-clamp-2">{event.detail}</div>
                                                <div className="text-xs text-muted-foreground/70">
                                                    {new Date(event.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} {event.user_name ? `· ${event.user_name}` : ''}
                                                </div>
                                            </div>
                                        </div>
                                    );
                                })
                            )}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};
