import React, { useEffect, useState } from 'react';
import { Users, UserPlus, Shield, AlertCircle, CheckCircle2, Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { accountsApi, User } from '../../api/accountsApi';
import { useAuthStore } from '../../store/authStore';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

const ROLE_BADGE_COLORS: Record<string, string> = {
    OWNER: 'bg-muted text-foreground border-border',
    ACCOUNTANT: 'bg-success/10 text-success border-success/20',
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
                    toast.error(t('errors.operationFailed'));
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
                    <Table className="w-full text-left border-collapse">
                        <TableHeader>
                            <TableRow className="bg-muted border-b border-border text-xs font-bold text-muted-foreground uppercase tracking-wider">
                                <TableHead className="p-4">{t('team.employee')}</TableHead>
                                <TableHead className="p-4">{t('team.role')}</TableHead>
                                <TableHead className="p-4">{t('team.status')}</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody className="divide-y divide-border">
                            {team.map((member) => (
                                <TableRow key={member.id} className="hover:bg-muted transition-colors">
                                    <TableCell className="p-4">
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
                                    </TableCell>
                                    <TableCell className="p-4">
                                        <span className={`inline-flex items-center px-2.5 py-1 rounded-md text-xs font-bold border ${member.workspace_role ? ROLE_BADGE_COLORS[member.workspace_role] : 'bg-muted text-muted-foreground border-border'}`}>
                                            {member.workspace_role ? t(`team.roles.${member.workspace_role}`) : t('team.employee')}
                                        </span>
                                    </TableCell>
                                    <TableCell className="p-4">
                                        <div className="flex items-center gap-1.5 text-xs font-medium text-success">
                                            <CheckCircle2 className="w-4 h-4" /> {t('team.active')}
                                        </div>
                                    </TableCell>
                                </TableRow>
                            ))}
                            {team.length === 0 && (
                                <TableRow>
                                    <TableCell colSpan={3} className="p-8 text-center text-muted-foreground">{t('team.noMembers')}</TableCell>
                                </TableRow>
                            )}
                        </TableBody>
                    </Table>
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
                        <div className="mt-4 flex items-center gap-2 text-sm text-destructive font-medium bg-destructive/10 p-3 rounded-lg border border-destructive/20">
                            <AlertCircle className="w-4 h-4 shrink-0" /> {error}
                        </div>
                    )}

                    {success && (
                        <div className="mt-4 flex items-center gap-2 text-sm text-success font-medium bg-success/10 p-3 rounded-lg border border-success/20">
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
