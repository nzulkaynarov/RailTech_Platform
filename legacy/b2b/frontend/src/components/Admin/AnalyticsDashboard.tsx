import React, { useState, useEffect, useCallback } from 'react';
import {
    TrendingUp,
    Users,
    BarChart3,
    PieChart,
    ArrowUpRight,
    PackageSearch,
    Loader2,
    Activity,
    Target,
    Zap
} from 'lucide-react';
import { crmApi, CRMAnalytics } from '../../api/crmApi';
import { useTaskStore } from '../../store/taskStore';
import { Button } from '@/components/ui/button';

export const AnalyticsDashboard: React.FC = () => {
    const [data, setData] = useState<CRMAnalytics | null>(null);
    const [loading, setLoading] = useState(true);
    const { activeTaskIds } = useTaskStore();

    const fetchAnalytics = useCallback(async (isSilent = false) => {
        if (!isSilent) setLoading(true);
        try {
            const results = await crmApi.getAnalytics();
            setData(results);
        } catch (error) {
            console.error('Failed to fetch analytics:', error);
        } finally {
            if (!isSilent) setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchAnalytics();
        
        // Auto-refresh every 60 seconds
        const interval = setInterval(() => fetchAnalytics(true), 60000);
        return () => clearInterval(interval);
    }, [fetchAnalytics]);

    // Refresh when tasks finish
    useEffect(() => {
        if (activeTaskIds.length === 0 && !loading) {
            fetchAnalytics(true);
        }
    }, [activeTaskIds.length, loading, fetchAnalytics]);

    if (loading) {
        return (
            <div className="flex flex-col items-center justify-center h-full gap-4">
                <Loader2 className="w-8 h-8 text-primary animate-spin" />
                <p className="text-xs font-black uppercase tracking-widest text-muted-foreground">Synchronizing Market Intelligence...</p>
            </div>
        );
    }

    if (!data) return null;

    const statusColors: { [key: string]: string } = {
        'Draft': 'bg-muted-foreground',
        'KYC Pending': 'bg-amber-500',
        'Calculating': 'bg-primary',
        'Quote Sent': 'bg-primary/80',
        'Contract Signed': 'bg-emerald-500',
    };

    const statusLabels: { [key: string]: string } = {
        'Draft': 'DRAFT_PROTOCOLS',
        'KYC Pending': 'KYC_VERIFICATION',
        'Calculating': 'VALUE_ENGINEERING',
        'Quote Sent': 'QUOTE_DISPATCHED',
        'Contract Signed': 'PARTNER_CONTRACTED',
    };

    return (
        <div className="p-4 h-full space-y-4 animate-in fade-in duration-300 font-mono">
            {/* Header */}
            <header className="flex items-end justify-between border-b border-border pb-3">
                <div>
                    <h1 className="text-xl font-black tracking-tight text-foreground uppercase leading-none">
                        Commercial <span className="text-primary">Intelligence</span>
                    </h1>
                    <p className="text-xs font-bold text-muted-foreground uppercase tracking-widest leading-none mt-1">
                        Operational Metrics & Revenue Exposure Analysis
                    </p>
                </div>
                
                <div className="flex items-center gap-4 text-[9px] font-black uppercase tracking-widest text-muted-foreground">
                    <div className="flex items-center gap-1.5 px-2 py-1 bg-emerald-500/5 border border-emerald-500/20 rounded text-emerald-500">
                        <Activity className="w-3 h-3" />
                        System_Stable
                    </div>
                </div>
            </header>

            {/* Top Cards Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
                <div className="bg-card p-4 rounded border border-border shadow-sm relative overflow-hidden group">
                    <div className="flex items-center justify-between mb-3">
                        <div className="w-8 h-8 rounded bg-[var(--color-chart-1)]/10 flex items-center justify-center text-[var(--color-chart-1)] border border-[var(--color-chart-1)]/20">
                            <TrendingUp className="w-4 h-4" />
                        </div>
                        <span className="text-xs font-black text-emerald-500">LIVE</span>
                    </div>
                    <p className="text-[9px] font-bold uppercase tracking-widest text-muted-foreground mb-1">Pipeline_Value</p>
                    <h3 className="text-xl font-black text-foreground">
                        ${data.total_pipeline_value.toLocaleString()}
                    </h3>
                </div>

                <div className="bg-card p-4 rounded border border-border shadow-sm relative overflow-hidden group">
                    <div className="flex items-center justify-between mb-3">
                        <div className="w-8 h-8 rounded bg-amber-500/10 flex items-center justify-center text-amber-600 border border-amber-500/20">
                            <PackageSearch className="w-4 h-4" />
                        </div>
                        <span className="text-xs font-black text-amber-500">URGENT</span>
                    </div>
                    <p className="text-[9px] font-bold uppercase tracking-widest text-muted-foreground mb-1">Sourcing_Backlog</p>
                    <h3 className="text-xl font-black text-foreground">
                        {data.sourcing_backlog} <span className="text-xs text-muted-foreground uppercase tracking-widest">SKUs</span>
                    </h3>
                </div>

                <div className="bg-card p-4 rounded border border-border shadow-sm relative overflow-hidden group">
                    <div className="flex items-center justify-between mb-3">
                        <div className="w-8 h-8 rounded bg-emerald-500/10 flex items-center justify-center text-emerald-600 border border-emerald-500/20">
                            <Users className="w-4 h-4" />
                        </div>
                        <span className="text-xs font-black text-emerald-500">STABLE</span>
                    </div>
                    <p className="text-[9px] font-bold uppercase tracking-widest text-muted-foreground mb-1">Conversion_Rate</p>
                    <h3 className="text-xl font-black text-foreground">
                        {data.conversion_rate || 0}%
                    </h3>
                </div>

                <div className="bg-card p-4 rounded border border-border shadow-sm relative overflow-hidden group">
                    <div className="flex items-center justify-between mb-3">
                        <div className="w-8 h-8 rounded bg-primary/10 flex items-center justify-center text-primary border border-primary/20">
                            <BarChart3 className="w-4 h-4" />
                        </div>
                        <span className="text-xs font-black text-primary">TARGET: 15%</span>
                    </div>
                    <p className="text-[9px] font-bold uppercase tracking-widest text-muted-foreground mb-1">Avg_Margin</p>
                    <h3 className="text-xl font-black text-foreground">
                        {data.avg_margin || 0}%
                    </h3>
                </div>
            </div>

            {/* Main Visual Section */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                {/* Pipeline Health */}
                <div className="lg:col-span-2 bg-card p-6 rounded border border-border shadow-sm flex flex-col">
                    <div className="flex items-center justify-between mb-6">
                        <div className="flex items-center gap-3">
                            <div className="w-8 h-8 rounded bg-foreground flex items-center justify-center text-background border border-border">
                                <PieChart className="w-4 h-4" />
                            </div>
                            <h4 className="text-[11px] font-black uppercase tracking-widest text-foreground">Commercial_Funnel_Dynamics</h4>
                        </div>
                        {activeTaskIds.length > 0 && (
                            <div className="flex items-center gap-2 text-[9px] font-black text-primary uppercase tracking-widest animate-pulse">
                                <Zap className="w-3 h-3" /> Processing_Feed
                            </div>
                        )}
                    </div>

                    <div className="space-y-5 flex-1 flex flex-col justify-center">
                        {data.pipeline_by_status.map((item) => {
                            const maxCount = Math.max(...data.pipeline_by_status.map(s => s.count));
                            const percentage = (item.count / maxCount) * 100;

                            return (
                                <div key={item.stage__name} className="group">
                                    <div className="flex justify-between items-center mb-1.5 px-0.5">
                                        <span className="text-xs font-black uppercase tracking-widest text-muted-foreground group-hover:text-foreground transition-colors">
                                            {statusLabels[item.stage__name] || item.stage__name}
                                        </span>
                                        <span className="text-xs font-black text-foreground">{item.count}</span>
                                    </div>
                                    <div className="h-2 w-full bg-muted rounded-sm overflow-hidden border border-border">
                                        <div
                                            className={`${statusColors[item.stage__name] || 'bg-primary'} h-full transition-all duration-700 ease-out`}
                                            style={{ width: `${percentage}%` }}
                                        ></div>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>

                {/* Sourcing Urgency */}
                <div className="bg-foreground p-6 rounded border border-border text-background shadow-xl relative overflow-hidden group">
                    <div className="relative z-10 flex flex-col h-full">
                        <div className="flex items-center gap-2 mb-6">
                            <Target className="w-5 h-5 text-primary" />
                            <h4 className="text-[11px] font-black uppercase tracking-widest">Sourcing_Efficiency_Index</h4>
                        </div>
                        
                        <div className="space-y-4 flex-1">
                            <div className="p-4 rounded bg-white/5 border border-white/10">
                                <p className="text-[9px] font-black uppercase tracking-widest text-primary mb-1">MAPPING_PRECISION</p>
                                <div className="text-2xl font-black tabular-nums">{data.mapped_items_percentage}%</div>
                                <div className="w-full h-1 bg-white/10 rounded-full mt-2 overflow-hidden">
                                    <div className="h-full bg-primary shadow-[0_0_8px_hsl(var(--primary)/0.5)] transition-all duration-1000" style={{ width: `${data.mapped_items_percentage}%` }}></div>
                                </div>
                            </div>
                            
                            <div className="p-4 rounded bg-white/5 border border-white/10">
                                <p className="text-[9px] font-black uppercase tracking-widest text-primary mb-1">AVG_DISCOVERY_LATENCY</p>
                                <div className="text-2xl font-black tabular-nums">{data.sourcing_speed_avg || 0}D</div>
                                <p className="text-[8px] text-muted-foreground mt-2 font-bold uppercase tracking-tight">Derived from 30-day transactional history</p>
                            </div>
                        </div>

                        <Button
                            onClick={() => window.location.href = '/crm/sourcing'}
                            className="mt-6 w-full py-2 text-xs font-black uppercase tracking-widest active:scale-95 group"
                        >
                            Open_Backlog_Registry
                            <ArrowUpRight className="w-3.5 h-3.5 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
                        </Button>
                    </div>
                </div>
            </div>
        </div>
    );
};
