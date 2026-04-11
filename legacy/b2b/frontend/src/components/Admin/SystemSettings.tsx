import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { DollarSign, Globe, Shield, Bell, Save, RefreshCw, CheckCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

export const SystemSettings: React.FC = () => {
    const { t } = useTranslation();
    const [activeTab, setActiveTab] = useState<'finance' | 'platform' | 'security' | 'notifications'>('finance');
    const [isSaving, setIsSaving] = useState(false);

    const [showSuccess, setShowSuccess] = useState(false);

    const handleSave = () => {
        setIsSaving(true);
        setShowSuccess(false);
        // TODO: Wire to backend API when settings endpoint is implemented
        toast.info(t('admin.systemSettings.saveNotAvailable'));
        setIsSaving(false);
    };

    const tabs = [
        { id: 'finance' as const, icon: DollarSign, label: t('admin.systemSettings.tabs.finance') },
        { id: 'platform' as const, icon: Globe, label: t('admin.systemSettings.tabs.platform') },
        { id: 'security' as const, icon: Shield, label: t('admin.systemSettings.tabs.security') },
        { id: 'notifications' as const, icon: Bell, label: t('admin.systemSettings.tabs.notifications') },
    ];

    return (
        <div className="p-6 md:p-10 max-w-7xl mx-auto h-full space-y-8 animate-in fade-in duration-500">
            <div>
                <h1 className="text-3xl font-black tracking-tight text-foreground mb-2">
                    {t('admin.systemSettings.title')} <span className="text-destructive">{t('admin.systemSettings.titleHighlight')}</span>
                </h1>
                <p className="text-muted-foreground font-medium">{t('admin.systemSettings.subtitle')}</p>
            </div>

            {showSuccess && (
                <div className="bg-success/10 border border-success/20 text-success p-4 rounded-2xl flex items-center gap-3 animate-in fade-in zoom-in-95 duration-300">
                    <CheckCircle className="w-5 h-5" />
                    <span className="font-bold">{t('admin.systemSettings.settingsSaved')}</span>
                </div>
            )}

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
                                            <Input type="number" defaultValue="12" className="font-bold" />
                                            <span className="absolute right-4 top-1/2 -translate-y-1/2 font-bold text-muted-foreground">%</span>
                                        </div>
                                    </div>
                                    <div>
                                        <label className="block text-xs font-bold text-muted-foreground uppercase tracking-wider mb-2">{t('admin.systemSettings.finance.standardMargin')}</label>
                                        <div className="relative">
                                            <Input type="number" defaultValue="15" className="font-bold" />
                                            <span className="absolute right-4 top-1/2 -translate-y-1/2 font-bold text-muted-foreground">%</span>
                                        </div>
                                    </div>
                                    <div>
                                        <label className="block text-xs font-bold text-muted-foreground uppercase tracking-wider mb-2">{t('admin.systemSettings.finance.exchangeRate')}</label>
                                        <Input type="text" readOnly value="12,500.00" className="bg-muted text-muted-foreground font-mono" />
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
                                        <div className="w-12 h-6 bg-muted-foreground/30 rounded-full relative cursor-pointer">
                                            <div className="absolute left-1 top-1 w-4 h-4 bg-background rounded-full transition-all"></div>
                                        </div>
                                    </div>
                                    <div>
                                        <label className="block text-xs font-bold text-muted-foreground uppercase tracking-wider mb-2">{t('admin.systemSettings.platform.platformName')}</label>
                                        <Input type="text" defaultValue="RailTech B2B Ecosystem" />
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
                                        <div className="w-12 h-6 bg-destructive rounded-full relative cursor-pointer">
                                            <div className="absolute right-1 top-1 w-4 h-4 bg-background rounded-full"></div>
                                        </div>
                                    </div>
                                    <Button variant="link" className="text-destructive p-0 h-auto font-bold">
                                        <RefreshCw className="w-4 h-4" /> {t('admin.systemSettings.security.resetSessions')}
                                    </Button>
                                </div>
                            </div>
                        )}

                        <div className="pt-8 border-t border-border flex gap-4">
                            <Button
                                onClick={handleSave}
                                disabled={isSaving}
                                variant="destructive"
                                size="lg"
                                className="rounded-2xl font-bold"
                            >
                                {isSaving ? <RefreshCw className="w-5 h-5 animate-spin" /> : <Save className="w-5 h-5" />}
                                {t('admin.systemSettings.saveChanges')}
                            </Button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};
