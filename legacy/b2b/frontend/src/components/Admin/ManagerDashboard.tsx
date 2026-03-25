import React from 'react';
import {
    FileText, Link2, ShieldCheck, DollarSign, ArrowRight,
    TrendingUp, Package, Clock, UserCheck, Activity, AlertTriangle
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { useDeals, useAnalytics } from '../../hooks/useCRM';

interface KPICardProps {
    icon: React.ElementType;
    label: string;
    value: string | number;
    sub?: string;
    color: string;
    trend?: string;
    link?: string;
}

const KPICard: React.FC<KPICardProps> = ({ icon: Icon, label, value, sub, color, trend, link }) => {
    const content = (
        <div className="h-full flex flex-col justify-between">
            <div className="flex items-center justify-between mb-2">
                <div className={`w-8 h-8 rounded flex items-center justify-center ${color} border border-border/50 shadow-inner`}>
                    <Icon className="w-4 h-4" />
                </div>
                {trend && (
                    <span className="flex items-center gap-1 text-[9px] font-black text-emerald-500 uppercase tracking-widest bg-emerald-500/5 px-1.5 py-0.5 rounded border border-emerald-500/20">
                        <TrendingUp className="w-2.5 h-2.5" />{trend}
                    </span>
                )}
            </div>
            <div>
                <div className="text-xl font-black text-foreground leading-none mb-0.5">{value}</div>
                <div className="text-[9px] font-bold text-muted-foreground  uppercase tracking-widest font-mono">{label}</div>
                {sub && <div className="text-[8px] font-medium text-muted-foreground  mt-1 uppercase tracking-tight">{sub}</div>}
            </div>
        </div>
    );

    const baseClass = "bg-card border border-border rounded p-4 group transition-all hover:border-primary/30 shadow-sm h-full block";

    if (link) {
        return (
            <Link to={link} className={baseClass}>
                {content}
            </Link>
        );
    }

    return (
        <div className={baseClass}>
            {content}
        </div>
    );
};

export const ManagerDashboard: React.FC = () => {
    const { data: deals = [], isLoading: dealsLoading } = useDeals();
    const { data: analytics, isLoading: analyticsLoading } = useAnalytics();
    
    const loading = dealsLoading || analyticsLoading;

    // Filter deals based on stage_name (supporting both Russian and English strings from legacy/current DB)
    const newLeads = deals.filter(d => d.stage_name === 'Черновик' || d.stage_name === 'Draft' || d.stage_name === 'Проверка KYC' || d.stage_name === 'KYC Check').length;
    const inProgress = deals.filter(d => d.stage_name === 'Расчет цен' || d.stage_name === 'Calculating' || d.stage_name === 'КП отправлено' || d.stage_name === 'Quote Sent').length;
    const contracted = deals.filter(d => d.stage_name === 'Договор подписан' || d.stage_name === 'Contract Signed').length;

    // Revenue calculation from total_value
    const totalSum = deals
        .filter(d => d.stage_name === 'Договор подписан' || d.stage_name === 'Contract Signed')
        .reduce((sum, d) => sum + parseFloat(d.total_value || '0'), 0);

    const sourcingPending = analytics?.sourcing_backlog ?? 0;
    const kycPendingCount = analytics?.kyc_backlog ?? 0;

    return (
        <div className="p-4 h-full space-y-4 animate-in fade-in duration-300">
            {/* Header / Command Center Title */}
            <div className="flex items-end justify-between border-b border-border pb-3">
                <div>
                    <h1 className="text-xl font-black tracking-tight text-foreground uppercase">
                        Sourcing <span className="text-primary">Commander</span>
                    </h1>
                    <p className="text-xs font-bold text-muted-foreground uppercase tracking-widest leading-none mt-1">
                        Operational Dashboard & Transaction Registry
                    </p>
                </div>
                <div className="hidden sm:flex items-center gap-2">
                    <div className="flex items-center gap-1.5 px-2 py-1 bg-primary/10 border border-primary/20 rounded text-primary text-[9px] font-bold uppercase tracking-widest">
                        <Activity className="w-3 h-3" />
                        Live Feed Active
                    </div>
                </div>
            </div>

            {/* KPI Grid */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                <KPICard icon={FileText} label="New Protocols" value={loading ? '—' : newLeads}
                    color="bg-primary/10 text-primary"
 link="/crm/home" />
                <KPICard icon={Clock} label="Operational P/L" value={loading ? '—' : inProgress}
                    color="bg-amber-500/10 text-amber-500" link="/crm/home" />
                <KPICard icon={DollarSign} label="Gross Exposure" value={loading ? '—' : `$${totalSum.toLocaleString()}`}
                    color="bg-emerald-500/10 text-emerald-500"
 link="/crm/analytics" />
                <KPICard icon={Package} label="Finalized Sales" value={loading ? '—' : contracted}
                    color="bg-primary/10 text-primary" link="/crm/analytics" />
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                {/* Pending Actions Board */}
                <div className="lg:col-span-1 space-y-3">
                    <div className="px-1 flex items-center justify-between">
                        <h2 className="text-xs font-black uppercase tracking-widest text-muted-foreground">Action Queue</h2>
                        <span className="px-1.5 py-0.5 bg-red-500/10 text-red-500 text-[8px] font-black rounded border border-red-500/20 animate-pulse">Critical</span>
                    </div>

                    <Link to="/crm/sourcing" className="block p-4 rounded bg-card border border-border hover:border-primary/30 hover:bg-muted transition-all group group shadow-sm">
                        <div className="flex items-center gap-4 mb-3">
                            <div className="w-9 h-9 rounded bg-primary/10 flex items-center justify-center border border-primary/20 shadow-inner">
                                <Link2 className="w-5 h-5 text-primary" />
                            </div>
                            <div>
                                <p className="text-2xl font-black text-foreground leading-none">{sourcingPending}</p>
                                <p className="text-[9px] font-bold text-muted-foreground  uppercase tracking-widest font-mono mt-1">Sourcing Backlog</p>
                            </div>
                        </div>
                        <div className="flex items-center justify-between text-[9px] font-bold text-muted-foreground uppercase tracking-tight pt-3 border-t border-border">
                            <span className="flex items-center gap-2"><AlertTriangle className="w-3 h-3 text-amber-500" /> Items requiring PIN mapping</span>
                            <ArrowRight className="w-3.5 h-3.5 text-muted-foreground group-hover:text-primary transition-colors" />
                        </div>
                    </Link>

                    <Link to="/crm/kyc" className="block p-4 rounded bg-card border border-border hover:border-primary/30 hover:bg-muted transition-all group shadow-sm">
                        <div className="flex items-center gap-4 mb-3">
                            <div className="w-9 h-9 rounded bg-primary/10 flex items-center justify-center border border-primary/20 shadow-inner">
                                <ShieldCheck className="w-5 h-5 text-primary" />
                            </div>
                            <div>
                                <p className="text-2xl font-black text-foreground leading-none">{kycPendingCount}</p>
                                <p className="text-[9px] font-bold text-muted-foreground  uppercase tracking-widest font-mono mt-1">KYC Verifications</p>
                            </div>
                        </div>
                        <div className="flex items-center justify-between text-[9px] font-bold text-muted-foreground uppercase tracking-tight pt-3 border-t border-border">
                            <span className="flex items-center gap-2"><Clock className="w-3 h-3" /> Entities at L1 restriction</span>
                            <ArrowRight className="w-3.5 h-3.5 text-muted-foreground group-hover:text-primary transition-colors" />
                        </div>
                    </Link>
                </div>

                {/* Recent Activity Pipeline */}
                <div className="lg:col-span-2">
                    <div className="bg-card border border-border rounded shadow-sm flex flex-col h-full font-mono overflow-hidden">
                        <div className="px-6 py-4 border-b border-border flex items-center justify-between bg-muted/50">
                            <h2 className="text-xs font-black text-foreground uppercase tracking-widest">Active Deal Pipeline</h2>
                            <Link to="/crm/home" className="text-[8px] font-bold text-primary hover:text-primary/80 uppercase tracking-widest transition-colors flex items-center gap-1">
                                Full Registry <ArrowRight className="w-3 h-3" />
                            </Link>
                        </div>

                        <div className="flex-1 divide-y divide-border">
                            {(loading ? [] : deals.slice(0, 7)).map((deal) => (
                                <Link to={`/crm/deals/${deal.id}`} key={deal.id} className="flex items-center justify-between p-4 hover:bg-muted transition-colors group">
                                    <div className="flex items-center gap-4 min-w-0">
                                        <div className="w-8 h-8 rounded bg-muted flex items-center justify-center border border-border shadow-sm">
                                            <FileText className="w-4 h-4 text-muted-foreground" />
                                        </div>
                                        <div className="min-w-0">
                                            <div className="flex items-center gap-2 mb-0.5">
                                                <p className="text-[11px] font-black text-foreground uppercase tracking-tight group-hover:text-primary transition-colors truncate">
                                                    DL_{deal.id.toString().padStart(6, '0')}
                                                </p>
                                                <span className={`text-[8px] font-black uppercase px-1.5 py-0.5 rounded border ${
                                                    deal.stage_name === 'Черновик' || deal.stage_name === 'Draft' ? 'bg-muted text-muted-foreground border-border' :
                                                    deal.stage_name === 'Проверка KYC' || deal.stage_name === 'KYC Check' ? 'bg-primary/10 text-primary border-primary/20' :
                                                    deal.stage_name === 'Расчет цен' || deal.stage_name === 'Calculating' ? 'bg-amber-500/10 text-amber-500 border-amber-500/20' :
                                                    deal.stage_name === 'КП отправлено' || deal.stage_name === 'Quote Sent' ? 'bg-primary/10 text-primary border-primary/20' :
                                                    'bg-emerald-500/10 text-emerald-500 border-emerald-500/20'
                                                }`}>
                                                    {deal.stage_name || 'System Draft'}
                                                </span>
                                            </div>
                                            <div className="flex items-center gap-3 text-[8px] text-muted-foreground font-bold uppercase tracking-widest truncate">
                                                <span className="flex items-center gap-1"><UserCheck className="w-2.5 h-2.5" /> {deal.company_name || '—'}</span>
                                                <span>•</span>
                                                <span className="flex items-center gap-1"><Package className="w-2.5 h-2.5" /> {(deal.active_quote?.items || []).length} SKU</span>
                                            </div>
                                        </div>
                                    </div>
                                    <div className="flex items-center gap-4 shrink-0">
                                        <div className="text-right hidden sm:block">
                                            <p className="text-xs font-black text-foreground">${parseFloat(deal.total_value || '0').toLocaleString()}</p>
                                            <p className="text-[8px] text-muted-foreground font-bold uppercase tracking-widest">Gross Value</p>
                                        </div>
                                        <ArrowRight className="w-4 h-4 text-muted-foreground group-hover:text-primary transition-colors ml-2" />
                                    </div>
                                </Link>
                            ))}
                            {!loading && deals.length === 0 && (
                                <div className="py-10 text-center text-xs font-bold text-muted-foreground uppercase tracking-widest">
                                    No active protocols found in pipeline
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};
