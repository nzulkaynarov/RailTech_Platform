import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { DollarSign, Globe, Shield, Save, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Skeleton } from '@/components/ui/LoadingSkeleton';
import { useSystemSettings, useUpdateSystemSettings } from '@/hooks/useSystemSettings';

type Tab = 'finance' | 'platform' | 'security';

export const SystemSettings: React.FC = () => {
    const { t } = useTranslation();
    const { data: settings, isLoading } = useSystemSettings();
    const updateMutation = useUpdateSystemSettings();

    const [activeTab, setActiveTab] = useState<Tab>('finance');

    // Local form state — synced from server data
    const [vatRate, setVatRate] = useState('');
    const [standardMargin, setStandardMargin] = useState('');
    const [exchangeRate, setExchangeRate] = useState('');
    const [platformName, setPlatformName] = useState('');
    const [maintenanceMode, setMaintenanceMode] = useState(false);
    const [twoFactorRequired, setTwoFactorRequired] = useState(false);

    // Sync local state when server data loads
    useEffect(() => {
        if (settings) {
            setVatRate(settings.vat_rate);
            setStandardMargin(settings.standard_margin);
            setExchangeRate(settings.exchange_rate_usd_uzs);
            setPlatformName(settings.platform_name);
            setMaintenanceMode(settings.maintenance_mode);
            setTwoFactorRequired(settings.is_two_factor_required);
        }
    }, [settings]);

    const handleSave = async () => {
        try {
            await updateMutation.mutateAsync({
                vat_rate: vatRate,
                standard_margin: standardMargin,
                exchange_rate_usd_uzs: exchangeRate,
                platform_name: platformName,
                maintenance_mode: maintenanceMode,
                is_two_factor_required: twoFactorRequired,
            });
            toast.success(t('admin.systemSettings.settingsSaved'));
        } catch {
            toast.error(t('common.error'));
        }
    };

    const tabs = [
        { id: 'finance' as const, icon: DollarSign, label: t('admin.systemSettings.tabs.finance') },
        { id: 'platform' as const, icon: Globe, label: t('admin.systemSettings.tabs.platform') },
        { id: 'security' as const, icon: Shield, label: t('admin.systemSettings.tabs.security') },
    ];

    if (isLoading) {
        return (
            <div className="p-6 md:p-10 max-w-7xl mx-auto space-y-8">
                <Skeleton className="h-10 w-64" />
                <Skeleton className="h-4 w-96" />
                <div className="flex gap-8">
                    <Skeleton className="h-48 w-72" />
                    <Skeleton className="h-48 flex-1" />
                </div>
            </div>
        );
    }

    return (
        <div className="p-6 md:p-10 max-w-7xl mx-auto h-full space-y-8 animate-in fade-in duration-500">
            <div>
                <h1 className="text-3xl font-black tracking-tight text-foreground mb-2">
                    {t('admin.systemSettings.title')} <span className="text-destructive">{t('admin.systemSettings.titleHighlight')}</span>
                </h1>
                <p className="text-muted-foreground font-medium">{t('admin.systemSettings.subtitle')}</p>
            </div>

            <div className="flex flex-col lg:flex-row gap-8">
                {/* Tabs Sidebar */}
                <div className="w-full lg:w-72 space-y-1">
                    {tabs.map(tab => (
                        <Button
                            key={tab.id}
                            variant={activeTab === tab.id ? 'destructive' : 'ghost'}
                            onClick={() => setActiveTab(tab.id)}
                            className="flex items-center gap-3 w-full justify-start px-5 py-4 h-auto rounded-2xl font-bold text-sm"
                        >
                            <tab.icon className="w-5 h-5" />
                            {tab.label}
                        </Button>
                    ))}
                </div>

                {/* Content Area */}
                <div className="flex-1 bg-card border border-border rounded-3xl p-8 shadow-sm">
                    <div className="max-w-3xl space-y-8">

                        {activeTab === 'finance' && (
                            <div className="space-y-6">
                                <h2 className="text-xl font-bold text-foreground border-b border-border pb-4">{t('admin.systemSettings.finance.title')}</h2>
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                                    <div>
                                        <label className="block text-xs font-bold text-muted-foreground uppercase tracking-wider mb-2">{t('admin.systemSettings.finance.vatRate')}</label>
                                        <div className="relative">
                                            <Input
                                                type="number"
                                                value={vatRate}
                                                onChange={e => setVatRate(e.target.value)}
                                                className="font-bold"
                                                step="0.01"
                                            />
                                            <span className="absolute right-4 top-1/2 -translate-y-1/2 font-bold text-muted-foreground">%</span>
                                        </div>
                                    </div>
                                    <div>
                                        <label className="block text-xs font-bold text-muted-foreground uppercase tracking-wider mb-2">{t('admin.systemSettings.finance.standardMargin')}</label>
                                        <div className="relative">
                                            <Input
                                                type="number"
                                                value={standardMargin}
                                                onChange={e => setStandardMargin(e.target.value)}
                                                className="font-bold"
                                                step="0.01"
                                            />
                                            <span className="absolute right-4 top-1/2 -translate-y-1/2 font-bold text-muted-foreground">%</span>
                                        </div>
                                    </div>
                                    <div>
                                        <label className="block text-xs font-bold text-muted-foreground uppercase tracking-wider mb-2">{t('admin.systemSettings.finance.exchangeRate')}</label>
                                        <Input
                                            type="number"
                                            value={exchangeRate}
                                            onChange={e => setExchangeRate(e.target.value)}
                                            className="font-mono font-bold"
                                            step="0.01"
                                        />
                                    </div>
                                </div>
                                <div className="p-4 bg-warning/10 border border-warning/20 rounded-xl text-xs text-warning leading-relaxed">
                                    {t('admin.systemSettings.finance.vatWarning')}
                                </div>
                            </div>
                        )}

                        {activeTab === 'platform' && (
                            <div className="space-y-6">
                                <h2 className="text-xl font-bold text-foreground border-b border-border pb-4">{t('admin.systemSettings.platform.title')}</h2>
                                <div className="space-y-4">
                                    <div className="flex items-center justify-between p-4 bg-muted rounded-2xl border border-border">
                                        <div>
                                            <div className="font-bold text-foreground">{t('admin.systemSettings.platform.maintenance')}</div>
                                            <div className="text-xs text-muted-foreground">{t('admin.systemSettings.platform.maintenanceDesc')}</div>
                                        </div>
                                        <Switch
                                            checked={maintenanceMode}
                                            onCheckedChange={setMaintenanceMode}
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-xs font-bold text-muted-foreground uppercase tracking-wider mb-2">{t('admin.systemSettings.platform.platformName')}</label>
                                        <Input
                                            type="text"
                                            value={platformName}
                                            onChange={e => setPlatformName(e.target.value)}
                                        />
                                    </div>
                                </div>
                            </div>
                        )}

                        {activeTab === 'security' && (
                            <div className="space-y-6">
                                <h2 className="text-xl font-bold text-foreground border-b border-border pb-4">{t('admin.systemSettings.security.title')}</h2>
                                <div className="space-y-4">
                                    <div className="flex items-center justify-between p-4 border border-border rounded-2xl">
                                        <div>
                                            <div className="font-bold text-foreground">{t('admin.systemSettings.security.twoFactor')}</div>
                                            <div className="text-xs text-muted-foreground">{t('admin.systemSettings.security.twoFactorDesc')}</div>
                                        </div>
                                        <Switch
                                            checked={twoFactorRequired}
                                            onCheckedChange={setTwoFactorRequired}
                                        />
                                    </div>
                                </div>
                            </div>
                        )}

                        <div className="pt-8 border-t border-border flex gap-4">
                            <Button
                                onClick={handleSave}
                                disabled={updateMutation.isPending}
                                variant="destructive"
                                size="lg"
                                className="rounded-2xl font-bold"
                            >
                                {updateMutation.isPending ? <Loader2 className="w-5 h-5 animate-spin" /> : <Save className="w-5 h-5" />}
                                {t('admin.systemSettings.saveChanges')}
                            </Button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};
