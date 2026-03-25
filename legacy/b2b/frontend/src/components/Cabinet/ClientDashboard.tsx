import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
    FileText, CheckCircle2, Clock, DollarSign, ArrowRight,
    Plus, Upload, Shield, Package,
} from 'lucide-react';
import { crmApi, Deal } from '../../api/crmApi';
import { useAuthStore } from '../../store/authStore';
import { KPICard } from '@/components/ui/KPICard';
import { EmptyState } from '@/components/ui/EmptyState';
import { StatusBadge, getDealStageVariant, getKycVariant } from '@/components/ui/StatusBadge';
import { TableSkeleton } from '@/components/ui/LoadingSkeleton';

export const ClientDashboard: React.FC = () => {
    const { t } = useTranslation();
    const { user, kyc_status } = useAuthStore();
    const [deals, setDeals] = useState<Deal[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const load = async () => {
            try {
                const data = await crmApi.getDeals();
                setDeals(Array.isArray(data) ? data : []);
            } catch {
                setDeals([]);
            } finally {
                setLoading(false);
            }
        };
        load();
    }, []);

    const totalDeals = deals.length;
    const terminalStages = ['CLOSED_WON', 'CLOSED_LOST'];
    const inProgress = deals.filter(d => {
        const code = String(d.stage || '');
        return !terminalStages.includes(code);
    }).length;
    const contracted = deals.filter(d => {
        const code = String(d.stage || '');
        return code === 'CLOSED_WON' || code === 'CONTRACT_SIGNED';
    }).length;
    const totalSum = deals.reduce((sum, d) => {
        const val = parseFloat(d.active_quote?.total_incl_vat || '0');
        return sum + val;
    }, 0);

    return (
        <div className="p-4 lg:p-6 h-full space-y-5">
            {/* Header */}
            <div className="flex items-end justify-between border-b border-border pb-3">
                <div>
                    <h1 className="text-xl font-bold tracking-tight text-foreground">
                        {t('dashboard.welcome', { name: user?.first_name || user?.company?.name || user?.email?.split('@')[0] || '' })}
                    </h1>
                    {user?.company?.name && (
                        <p className="text-sm text-muted-foreground mt-0.5">
                            {user.company.name}
                        </p>
                    )}
                </div>
            </div>

            {/* KYC Banner */}
            {kyc_status && kyc_status !== 'L3_CONTRACTED' && (
                <div className="flex items-center gap-4 p-4 rounded-xl border bg-amber-50 dark:bg-amber-900/10 border-amber-200 dark:border-amber-500/20">
                    <div className="w-10 h-10 rounded-lg flex items-center justify-center bg-background border border-amber-200 dark:border-amber-500/20 shrink-0">
                        <Shield className="w-5 h-5 text-amber-500" />
                    </div>
                    <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-0.5">
                            <StatusBadge
                                label={t(`kyc.status.${kyc_status}`)}
                                variant={getKycVariant(kyc_status)}
                                size="sm"
                            />
                        </div>
                        <p className="text-sm text-muted-foreground">
                            {kyc_status === 'L1_UNVERIFIED'
                                ? t('kyc.banner.unverified')
                                : t('kyc.banner.verified')}
                        </p>
                    </div>
                    <Link
                        to="/cabinet/profile"
                        className="shrink-0 flex items-center gap-2 text-sm font-semibold px-4 py-2 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-colors focus-ring"
                    >
                        {kyc_status === 'L1_UNVERIFIED' ? t('kyc.banner.action') : t('nav.profile')}
                        <ArrowRight className="w-4 h-4" />
                    </Link>
                </div>
            )}

            {/* KPI Grid */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                <KPICard
                    icon={<FileText className="w-4 h-4 text-primary" />}
                    label={t('dashboard.kpi.registryVolume')}
                    value={totalDeals}
                    isLoading={loading}
                />
                <KPICard
                    icon={<Clock className="w-4 h-4 text-amber-500" />}
                    label={t('dashboard.kpi.activePipeline')}
                    value={inProgress}
                    isLoading={loading}
                />
                <KPICard
                    icon={<CheckCircle2 className="w-4 h-4 text-emerald-500" />}
                    label={t('dashboard.kpi.closedDeals')}
                    value={contracted}
                    isLoading={loading}
                />
                <KPICard
                    icon={<DollarSign className="w-4 h-4 text-purple-500" />}
                    label={t('dashboard.kpi.economicExposure')}
                    value={loading ? '...' : `$${totalSum.toLocaleString('ru-RU')}`}
                    isLoading={loading}
                />
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                {/* Recent Deals */}
                <div className="lg:col-span-2">
                    <div className="bg-card border border-border rounded-xl shadow-sm flex flex-col h-full overflow-hidden">
                        <div className="px-5 py-3.5 border-b border-border flex items-center justify-between">
                            <h2 className="text-sm font-bold text-foreground">
                                {t('dashboard.deals.title')}
                            </h2>
                            <Link
                                to="/cabinet/deals"
                                className="text-xs font-semibold text-primary hover:text-primary/80 transition-colors flex items-center gap-1 focus-ring rounded"
                            >
                                {t('common.showMore')} <ArrowRight className="w-3.5 h-3.5" />
                            </Link>
                        </div>

                        <div className="flex-1">
                            {loading ? (
                                <table className="w-full">
                                    <TableSkeleton rows={3} columns={4} />
                                </table>
                            ) : deals.length === 0 ? (
                                <EmptyState
                                    icon={<Package className="w-7 h-7 text-muted-foreground" />}
                                    title={t('dashboard.deals.emptyState')}
                                    description={t('dashboard.deals.emptyStateHint')}
                                    action={{
                                        label: t('dashboard.deals.createRFQ'),
                                        onClick: () => { window.location.href = '/cabinet/deals'; },
                                    }}
                                    className="py-10"
                                />
                            ) : (
                                <div className="divide-y divide-border">
                                    {deals.slice(0, 5).map(deal => (
                                        <Link
                                            to="/cabinet/deals"
                                            key={deal.id}
                                            className="flex items-center justify-between px-5 py-3.5 hover:bg-muted transition-colors group focus-ring"
                                        >
                                            <div className="flex items-center gap-3">
                                                <div className="w-8 h-8 rounded-lg bg-muted flex items-center justify-center border border-border">
                                                    <FileText className="w-4 h-4 text-muted-foreground" />
                                                </div>
                                                <div>
                                                    <p className="text-sm font-semibold text-foreground group-hover:text-primary transition-colors">
                                                        {t('dashboard.deals.title')} #{deal.id.toString().substring(0, 8)}
                                                    </p>
                                                    <p className="text-xs text-muted-foreground">
                                                        {(deal.active_quote?.items || []).length} {t('catalog.totalItems', { count: (deal.active_quote?.items || []).length }).split(' ')[0]}
                                                    </p>
                                                </div>
                                            </div>
                                            <div className="flex items-center gap-4">
                                                <div className="text-right hidden sm:block">
                                                    <p className="text-sm font-semibold text-foreground tabular-nums">
                                                        ${parseFloat(deal.active_quote?.total_incl_vat || '0').toLocaleString('ru-RU')}
                                                    </p>
                                                </div>
                                                <StatusBadge
                                                    label={deal.stage_name || t('dashboard.stages.NEW')}
                                                    variant={getDealStageVariant(String(deal.stage || 'NEW'))}
                                                />
                                                <ArrowRight className="w-4 h-4 text-muted-foreground group-hover:text-primary transition-colors" />
                                            </div>
                                        </Link>
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>
                </div>

                {/* Quick Actions */}
                <div className="lg:col-span-1">
                    <div className="bg-card border border-border rounded-xl p-5 shadow-sm h-full flex flex-col">
                        <h2 className="text-sm font-bold text-foreground mb-4 pb-2 border-b border-border">
                            {t('dashboard.quickActions')}
                        </h2>
                        <div className="space-y-3">
                            <QuickActionItem
                                to="/cabinet/deals"
                                icon={<Plus className="w-5 h-5" />}
                                iconColor="bg-primary/10 text-primary border-primary/20"
                                title={t('dashboard.deals.createRFQ')}
                                hoverColor="hover:border-primary/30"
                            />
                            <QuickActionItem
                                to="/cabinet/deals"
                                icon={<Upload className="w-5 h-5" />}
                                iconColor="bg-emerald-500/10 text-emerald-600 border-emerald-500/20"
                                title={t('dashboard.deals.bulkImport')}
                                hoverColor="hover:border-emerald-500/30"
                            />
                            <QuickActionItem
                                to="/cabinet/profile"
                                icon={<Shield className="w-5 h-5" />}
                                iconColor="bg-purple-500/10 text-purple-600 border-purple-500/20"
                                title={t('dashboard.deals.complianceData')}
                                hoverColor="hover:border-purple-500/30"
                            />
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};

/* ─── Quick Action sub-component ─── */
interface QuickActionItemProps {
    to: string;
    icon: React.ReactNode;
    iconColor: string;
    title: string;
    hoverColor: string;
}

const QuickActionItem: React.FC<QuickActionItemProps> = ({ to, icon, iconColor, title, hoverColor }) => (
    <Link
        to={to}
        className={`flex items-center gap-3 p-3.5 rounded-lg border border-border ${hoverColor} hover:bg-muted transition-colors group focus-ring`}
    >
        <div className={`w-9 h-9 rounded-lg flex items-center justify-center border ${iconColor}`}>
            {icon}
        </div>
        <span className="text-sm font-semibold text-foreground group-hover:text-primary transition-colors flex-1">
            {title}
        </span>
        <ArrowRight className="w-4 h-4 text-muted-foreground group-hover:text-primary transition-colors" />
    </Link>
);
