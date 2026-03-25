import React, { useEffect, useState } from 'react';
import { Users, UserPlus, Shield, AlertCircle, CheckCircle2, Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { accountsApi, User } from '../../api/accountsApi';
import { useAuthStore } from '../../store/authStore';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/select';

const ROLE_BADGE_COLORS: Record<string, string> = {
    OWNER: 'bg-muted text-foreground border-border',
    ACCOUNTANT: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400 border-emerald-200 dark:border-emerald-800',
    MANAGER: 'bg-muted text-foreground border-border',
};

export const CompanyTeamSettings: React.FC = () => {
    const { user } = useAuthStore();
    const { t } = useTranslation();
    const [team, setTeam] = useState<User[]>([]);
    const [loading, setLoading] = useState(true);
    const [inviting, setInviting] = useState(false);

    // Form state
    const [email, setEmail] = useState('');
    const [role, setRole] = useState('MANAGER');
    const [error, setError] = useState('');
    const [success, setSuccess] = useState('');

    const isOwner = user?.workspace_role === 'OWNER';

    useEffect(() => {
        const load = async () => {
            if (user?.company?.id) {
                try {
                    const data = await accountsApi.getTeam(user.company.id);
                    setTeam(data);
                } catch (err) {
                    console.error('Failed to load team', err);
                }
            }
            setLoading(false);
        };
        load();
    }, [user]);

    const handleInvite = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!user?.company?.id) return;

        setError('');
        setSuccess('');
        setInviting(true);

        try {
            const newUser = await accountsApi.inviteUser(user.company.id, { email, role });
            setTeam(prev => [...prev, newUser]);
            setSuccess(t('team.inviteSuccess', { email }));
            setEmail('');
        } catch (err: unknown) {
            const errorMessage = err instanceof Error ? err.message : t('team.inviteError');
            setError(errorMessage);
        } finally {
            setInviting(false);
        }
    };

    if (loading) return (
        <div className="flex p-10 justify-center">
            <Loader2 className="w-8 h-8 text-muted-foreground animate-spin" />
        </div>
    );

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between">
                <div>
                    <h3 className="text-xl font-bold text-foreground flex items-center gap-2">
                        <Users className="w-5 h-5 text-primary" />
                        {t('team.title')}
                    </h3>
                    <p className="text-sm text-muted-foreground mt-1">{t('team.subtitle')}</p>
                </div>
            </div>

            {/* Team List */}
            <div className="bg-card border border-border rounded-2xl overflow-hidden">
                <div className="overflow-x-auto">
                    <table className="w-full text-left border-collapse">
                        <thead>
                            <tr className="bg-muted border-b border-border text-xs font-bold text-muted-foreground uppercase tracking-wider">
                                <th className="p-4">{t('team.employee')}</th>
                                <th className="p-4">{t('team.role')}</th>
                                <th className="p-4">{t('team.status')}</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-border">
                            {team.map((member) => (
                                <tr key={member.id} className="hover:bg-muted transition-colors">
                                    <td className="p-4">
                                        <div className="flex items-center gap-3">
                                            <div className="w-10 h-10 rounded-full bg-muted flex items-center justify-center text-muted-foreground font-bold">
                                                {member.email.charAt(0).toUpperCase()}
                                            </div>
                                            <div>
                                                <div className="font-bold text-foreground text-sm">
                                                    {member.first_name || member.username} {member.id === user?.id && <span className="text-xs text-muted-foreground ml-2 font-normal">{t('team.itsYou')}</span>}
                                                </div>
                                                <div className="text-xs text-muted-foreground">{member.email}</div>
                                            </div>
                                        </div>
                                    </td>
                                    <td className="p-4">
                                        <span className={`inline-flex items-center px-2.5 py-1 rounded-md text-xs font-bold border ${member.workspace_role ? ROLE_BADGE_COLORS[member.workspace_role] : 'bg-muted text-muted-foreground border-border'}`}>
                                            {member.workspace_role ? t(`team.roles.${member.workspace_role}`) : t('team.employee')}
                                        </span>
                                    </td>
                                    <td className="p-4">
                                        <div className="flex items-center gap-1.5 text-xs font-medium text-emerald-600 dark:text-emerald-400">
                                            <CheckCircle2 className="w-4 h-4" /> {t('team.active')}
                                        </div>
                                    </td>
                                </tr>
                            ))}
                            {team.length === 0 && (
                                <tr>
                                    <td colSpan={3} className="p-8 text-center text-muted-foreground">{t('team.noMembers')}</td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            </div>

            {/* Invite Form (Owners only) */}
            {isOwner && (
                <div className="bg-muted border border-border rounded-2xl p-6">
                    <h4 className="text-base font-bold text-foreground mb-4 flex items-center gap-2">
                        <UserPlus className="w-4 h-4 text-primary" />
                        {t('team.invite')}
                    </h4>

                    <form onSubmit={handleInvite} className="flex flex-col md:flex-row gap-4 items-start">
                        <div className="flex-1 w-full">
                            <label className="sr-only">Email</label>
                            <Input
                                type="email"
                                value={email}
                                onChange={e => setEmail(e.target.value)}
                                placeholder={t('team.emailPlaceholder')}
                                required
                            />
                        </div>
                        <div className="w-full md:w-48">
                            <label className="sr-only">{t('team.role')}</label>
                            <Select value={role} onValueChange={setRole}>
                                <SelectTrigger className="w-full">
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="MANAGER">{t('team.roleOptions.MANAGER')}</SelectItem>
                                    <SelectItem value="ACCOUNTANT">{t('team.roleOptions.ACCOUNTANT')}</SelectItem>
                                </SelectContent>
                            </Select>
                        </div>
                        <Button
                            type="submit"
                            disabled={inviting || !email}
                            className="w-full md:w-auto"
                        >
                            {inviting ? <Loader2 className="w-4 h-4 animate-spin" /> : t('common.send')}
                        </Button>
                    </form>

                    {error && (
                        <div className="mt-4 flex items-center gap-2 text-sm text-rose-500 font-medium bg-rose-50 dark:bg-rose-500/10 p-3 rounded-lg border border-rose-200 dark:border-rose-500/20">
                            <AlertCircle className="w-4 h-4 shrink-0" /> {error}
                        </div>
                    )}

                    {success && (
                        <div className="mt-4 flex items-center gap-2 text-sm text-emerald-600 dark:text-emerald-400 font-medium bg-emerald-50 dark:bg-emerald-500/10 p-3 rounded-lg border border-emerald-200 dark:border-emerald-500/20">
                            <CheckCircle2 className="w-4 h-4 shrink-0" /> {success}
                        </div>
                    )}
                </div>
            )}

            {!isOwner && (
                <div className="flex items-center gap-3 p-4 bg-muted rounded-xl border border-border">
                    <Shield className="w-5 h-5 text-muted-foreground" />
                    <p className="text-sm text-muted-foreground font-medium">{t('team.ownerOnly')}</p>
                </div>
            )}
        </div>
    );
};
