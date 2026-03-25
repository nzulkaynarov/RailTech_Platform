import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { User as UserIcon, Shield, Key, Camera, UserCheck, RefreshCw, CheckCircle, Save, ShieldCheck } from 'lucide-react';
import { useAuthStore } from '../../store/authStore';
import { accountsApi } from '../../api/accountsApi';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

export const AdminProfile: React.FC = () => {
    const { t } = useTranslation();
    const { user, initAuth } = useAuthStore();
    const [isSaving, setIsSaving] = useState(false);
    const [activeTab, setActiveTab] = useState<'profile' | 'password'>('profile');

    // Profile state
    const [formData, setFormData] = useState({
        first_name: user?.first_name || '',
        last_name: user?.last_name || '',
        email: user?.email || '',
        phone: user?.phone || '',
    });

    // Password state
    const [passwordData, setPasswordData] = useState({
        current: '',
        new: '',
        confirm: '',
    });

    const [message, setMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null);

    useEffect(() => {
        if (user) {
            setFormData({
                first_name: user.first_name || '',
                last_name: user.last_name || '',
                email: user.email || '',
                phone: user.phone || '',
            });
        }
    }, [user]);

    const handleSaveProfile = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!user?.id) return;

        setIsSaving(true);
        setMessage(null);
        try {
            await accountsApi.updateUser(user.id, {
                first_name: formData.first_name,
                last_name: formData.last_name,
                phone: formData.phone,
            });
            await initAuth(); // Refresh global auth state
            setMessage({ type: 'success', text: t('admin.profile.profileUpdated') });
        } catch (err: unknown) {
            const error = err as { response?: { data?: { detail?: string } }, message?: string };
            setMessage({ type: 'error', text: error.response?.data?.detail || error.message || t('admin.profile.profileSaveError') });
        } finally {
            setIsSaving(false);
        }
    };

    const handleChangePassword = async (e: React.FormEvent) => {
        e.preventDefault();
        if (passwordData.new !== passwordData.confirm) {
            setMessage({ type: 'error', text: t('admin.profile.passwordMismatch') });
            return;
        }

        setIsSaving(true);
        setMessage(null);
        try {
            await accountsApi.changePassword({
                current_password: passwordData.current,
                new_password: passwordData.new,
            });
            setMessage({ type: 'success', text: t('admin.profile.passwordChanged') });
            setPasswordData({ current: '', new: '', confirm: '' });
        } catch (err: unknown) {
            const error = err as { response?: { data?: { current_password?: string[] } } };
            const errorMsg = error.response?.data?.current_password?.[0] || t('admin.profile.passwordChangeError');
            setMessage({ type: 'error', text: errorMsg });
        } finally {
            setIsSaving(false);
        }
    };

    return (
        <div className="p-6 md:p-10 max-w-4xl mx-auto h-full space-y-8 animate-in fade-in duration-500">
            <div>
                <h1 className="text-3xl font-black tracking-tight text-foreground mb-2">
                    {t('admin.profile.title')} <span className="text-destructive">{t('admin.profile.titleHighlight')}</span>
                </h1>
                <p className="text-muted-foreground font-medium">{t('admin.profile.subtitle')}</p>
            </div>

            {message && (
                <div className={`p-4 rounded-2xl flex items-center gap-3 animate-in fade-in zoom-in-95 duration-300 ${
                    message.type === 'success' ? 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-500' : 'bg-destructive/10 border border-destructive/20 text-destructive'
                }`}>
                    <CheckCircle className="w-5 h-5" />
                    <span className="font-bold">{message.text}</span>
                </div>
            )}

            <div className="flex flex-col md:flex-row gap-8">
                {/* Tabs */}
                <div className="w-full md:w-64 space-y-1">
                    <Button
                        variant={activeTab === 'profile' ? 'destructive' : 'ghost'}
                        onClick={() => setActiveTab('profile')}
                        className="flex items-center gap-3 w-full justify-start px-5 py-4 h-auto rounded-2xl font-bold text-sm"
                    >
                        <UserIcon className="w-5 h-5" /> {t('admin.profile.personalData')}
                    </Button>
                    <Button
                        variant={activeTab === 'password' ? 'destructive' : 'ghost'}
                        onClick={() => setActiveTab('password')}
                        className="flex items-center gap-3 w-full justify-start px-5 py-4 h-auto rounded-2xl font-bold text-sm"
                    >
                        <Key className="w-5 h-5" /> {t('admin.profile.security')}
                    </Button>

                    <div className="mt-8 pt-8 border-t border-border flex flex-col gap-3">
                        <div className="flex items-center gap-2 text-sm text-muted-foreground">
                            <UserCheck className="w-4 h-4 text-emerald-500" />
                            {t('admin.profile.accountVerified')}
                        </div>
                        <div className="flex items-center gap-2 text-sm text-muted-foreground">
                            <Shield className="w-4 h-4 text-primary" />
                            {t('admin.profile.fullAccess')}
                        </div>
                    </div>
                </div>

                {/* Forms */}
                <div className="flex-1 bg-card border border-border rounded-3xl p-8 shadow-sm">
                    {activeTab === 'profile' ? (
                        <form onSubmit={handleSaveProfile} className="space-y-6">
                            <div className="flex items-center gap-6 mb-8">
                                <div className="relative inline-block">
                                    <div className="w-20 h-20 rounded-3xl bg-gradient-to-br from-red-500 to-rose-600 flex items-center justify-center text-white text-2xl font-black shadow-xl">
                                        {user?.first_name?.[0]}{user?.last_name?.[0]}
                                    </div>
                                    <Button type="button" variant="outline" size="icon-xs" className="absolute -bottom-1 -right-1 rounded-lg shadow-lg">
                                        <Camera className="w-4 h-4" />
                                    </Button>
                                </div>
                                <div>
                                    <div className="text-xl font-black text-foreground">{user?.first_name} {user?.last_name}</div>
                                    <div className="text-xs font-bold text-destructive uppercase tracking-widest">{t('admin.profile.superAdmin')}</div>
                                </div>
                            </div>

                            <h3 className="text-lg font-bold text-foreground flex items-center gap-2 mb-4">
                                <UserIcon className="w-5 h-5 text-destructive" /> {t('admin.profile.mainData')}
                            </h3>

                            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                                <div>
                                    <label className="block text-xs font-bold text-muted-foreground uppercase tracking-wider mb-2">{t('admin.profile.firstName')}</label>
                                    <Input
                                        type="text"
                                        value={formData.first_name}
                                        onChange={e => setFormData({...formData, first_name: e.target.value})}
                                    />
                                </div>
                                <div>
                                    <label className="block text-xs font-bold text-muted-foreground uppercase tracking-wider mb-2">{t('admin.profile.lastName')}</label>
                                    <Input
                                        type="text"
                                        value={formData.last_name}
                                        onChange={e => setFormData({...formData, last_name: e.target.value})}
                                    />
                                </div>
                                <div className="md:col-span-2">
                                    <label className="block text-xs font-bold text-muted-foreground uppercase tracking-widest mb-2">{t('admin.profile.workEmail')}</label>
                                    <Input type="email" readOnly value={user?.email} className="bg-muted text-muted-foreground cursor-not-allowed" />
                                </div>
                                <div className="md:col-span-2">
                                    <label className="block text-xs font-bold text-muted-foreground uppercase tracking-widest mb-2">{t('admin.profile.phone')}</label>
                                    <Input
                                        type="tel"
                                        value={formData.phone}
                                        onChange={e => setFormData({...formData, phone: e.target.value})}
                                    />
                                </div>
                            </div>

                            <div className="pt-6">
                                <Button
                                    type="submit"
                                    disabled={isSaving}
                                    variant="destructive"
                                    size="lg"
                                    className="rounded-2xl font-bold"
                                >
                                    {isSaving ? <RefreshCw className="w-5 h-5 animate-spin" /> : <Save className="w-5 h-5" />}
                                    {isSaving ? t('common.updating') : t('admin.profile.saveProfile')}
                                </Button>
                            </div>
                        </form>
                    ) : (
                        <form onSubmit={handleChangePassword} className="space-y-6">
                            <h2 className="text-xl font-bold text-foreground mb-6">{t('admin.profile.changePassword')}</h2>
                            <div className="space-y-6 max-w-md">
                                <div>
                                    <label className="block text-xs font-bold text-muted-foreground uppercase tracking-wider mb-2">{t('admin.profile.currentPassword')}</label>
                                    <Input
                                        type="password"
                                        required
                                        value={passwordData.current}
                                        onChange={e => setPasswordData({...passwordData, current: e.target.value})}
                                    />
                                </div>
                                <div className="h-px bg-border my-2"></div>
                                <div>
                                    <label className="block text-xs font-bold text-muted-foreground uppercase tracking-wider mb-2">{t('admin.profile.newPassword')}</label>
                                    <Input
                                        type="password"
                                        required
                                        value={passwordData.new}
                                        onChange={e => setPasswordData({...passwordData, new: e.target.value})}
                                    />
                                </div>
                                <div>
                                    <label className="block text-xs font-bold text-muted-foreground uppercase tracking-wider mb-2">{t('admin.profile.confirmPassword')}</label>
                                    <Input
                                        type="password"
                                        required
                                        value={passwordData.confirm}
                                        onChange={e => setPasswordData({...passwordData, confirm: e.target.value})}
                                    />
                                </div>
                            </div>
                            <div className="pt-6">
                                <Button
                                    type="submit"
                                    disabled={isSaving}
                                    variant="destructive"
                                    size="lg"
                                    className="rounded-2xl font-bold"
                                >
                                    {isSaving ? <RefreshCw className="w-5 h-5 animate-spin" /> : <ShieldCheck className="w-5 h-5" />}
                                    {t('admin.profile.updatePassword')}
                                </Button>
                            </div>
                        </form>
                    )}
                </div>
            </div>
        </div>
    );
};
