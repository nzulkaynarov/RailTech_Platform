import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, Search, Briefcase, Edit, Trash2, Shield, MoreHorizontal, Users } from 'lucide-react';
import { User, Company } from '@/api/accountsApi';
import { useAuthStore } from '@/store/authStore';
import { UserSlidePanel } from './UserSlidePanel';
import { useUsers, useCreateUser, useUpdateUser, useDeleteUser, useToggleUserActive } from '@/hooks/useAccounts';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/select';
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator } from '@/components/ui/dropdown-menu';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { toast } from 'sonner';

const ROLE_BADGES: Record<string, { label: string; variant: 'default' | 'secondary' | 'destructive' | 'outline' }> = {
    'ADMIN': { label: 'SYS_ADMIN', variant: 'default' },
    'SALES_MANAGER': { label: 'SALES_OPS', variant: 'secondary' },
    'ACCOUNT_MANAGER': { label: 'ACC_EXEC', variant: 'secondary' },
    'CLIENT': { label: 'EXT_PARTNER', variant: 'outline' },
    'GUEST': { label: 'AUDIT_ONLY', variant: 'outline' },
};

export const AdminUsers: React.FC = () => {
    const { t } = useTranslation();
    const { user: currentUser } = useAuthStore();

    // UI states
    const [searchQuery, setSearchQuery] = useState('');
    const [filterRole, setFilterRole] = useState<string>('ALL');
    const [isPanelOpen, setIsPanelOpen] = useState(false);
    const [selectedUser, setSelectedUser] = useState<User | null>(null);
    const [deleteDialogUser, setDeleteDialogUser] = useState<User | null>(null);

    // React Query Hooks
    const { data: users = [], isLoading } = useUsers({
        search: searchQuery || undefined,
        role: filterRole === 'ALL' ? undefined : filterRole,
    });

    const createMutation = useCreateUser();
    const updateMutation = useUpdateUser();
    const deleteMutation = useDeleteUser();
    const toggleMutation = useToggleUserActive();

    const toggleStatus = async (user: User) => {
        if (user.id === currentUser?.id) return;
        try {
            await toggleMutation.mutateAsync(user.id);
        } catch (error) {
            console.error('Failed to toggle status', error);
        }
    };

    const handleEditClick = (user: User) => {
        setSelectedUser(user);
        setIsPanelOpen(true);
    };

    const handleCreateClick = () => {
        setSelectedUser(null);
        setIsPanelOpen(true);
    };

    const handleDeleteUser = async () => {
        if (!deleteDialogUser || deleteDialogUser.id === currentUser?.id) return;
        try {
            await deleteMutation.mutateAsync(deleteDialogUser.id);
        } catch (error) {
            console.error('Failed to delete user', error);
        } finally {
            setDeleteDialogUser(null);
        }
    };

    const handleSavePanel = async (data: Partial<User>) => {
        try {
            if (selectedUser) {
                await updateMutation.mutateAsync({ id: selectedUser.id, data });
            } else {
                await createMutation.mutateAsync(data);
            }
            setIsPanelOpen(false);
            setSelectedUser(null);
        } catch (error: unknown) {
            const e = error as { response?: { data?: { detail?: string } }; message?: string };
            toast.error(e.response?.data?.detail || e.message || t('errors.unknown'));
        }
    };

    return (
        <Card className="h-full flex flex-col">
            <CardHeader className="border-b">
                <div className="flex items-center justify-between">
                    <div>
                        <CardTitle className="text-xl font-black tracking-tight uppercase">
                            {t('admin.users.title')} <span className="text-primary">{t('admin.users.registry')}</span>
                        </CardTitle>
                        <CardDescription className="text-xs font-bold uppercase tracking-widest mt-1">
                            {t('admin.users.description')}
                        </CardDescription>
                    </div>
                    <Button size="sm" onClick={handleCreateClick}>
                        <Plus className="size-4" />
                        {t('admin.users.provision')}
                    </Button>
                </div>
            </CardHeader>

            <CardContent className="flex flex-col gap-4 flex-1 overflow-hidden pt-4">
                {/* Toolbar */}
                <div className="flex flex-col md:flex-row gap-2 items-center">
                    <div className="relative flex-1 w-full">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
                        <Input
                            type="text"
                            placeholder={t('admin.users.searchPlaceholder')}
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            className="pl-9"
                        />
                    </div>
                    <Select value={filterRole} onValueChange={setFilterRole}>
                        <SelectTrigger className="w-[180px]">
                            <SelectValue placeholder={t('admin.users.filterByRole')} />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="ALL">{t('admin.users.allRoles')}</SelectItem>
                            <SelectItem value="ADMIN">{t('roles.ADMIN')}</SelectItem>
                            <SelectItem value="SALES_MANAGER">{t('roles.SALES_MANAGER')}</SelectItem>
                            <SelectItem value="ACCOUNT_MANAGER">{t('roles.ACCOUNT_MANAGER')}</SelectItem>
                            <SelectItem value="CLIENT">{t('roles.CLIENT')}</SelectItem>
                            <SelectItem value="GUEST">{t('roles.GUEST')}</SelectItem>
                        </SelectContent>
                    </Select>
                </div>

                {/* Data Table */}
                <div className="flex-1 overflow-auto rounded-md border">
                    <Table>
                        <TableHeader className="sticky top-0 z-10 bg-muted">
                            <TableRow>
                                <TableHead>{t('admin.users.columns.user')}</TableHead>
                                <TableHead>{t('admin.users.columns.role')}</TableHead>
                                <TableHead>{t('admin.users.columns.company')}</TableHead>
                                <TableHead>{t('admin.users.columns.status')}</TableHead>
                                <TableHead className="text-right">{t('admin.users.columns.actions')}</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {isLoading ? (
                                Array.from({ length: 5 }).map((_, i) => (
                                    <TableRow key={i}>
                                        <TableCell>
                                            <div className="flex items-center gap-3">
                                                <Skeleton className="size-8 rounded-full" />
                                                <div className="space-y-1.5">
                                                    <Skeleton className="h-3.5 w-28" />
                                                    <Skeleton className="h-3 w-40" />
                                                </div>
                                            </div>
                                        </TableCell>
                                        <TableCell><Skeleton className="h-5 w-20" /></TableCell>
                                        <TableCell><Skeleton className="h-3.5 w-24" /></TableCell>
                                        <TableCell><Skeleton className="h-5 w-10" /></TableCell>
                                        <TableCell><Skeleton className="h-8 w-8 ml-auto" /></TableCell>
                                    </TableRow>
                                ))
                            ) : users.length === 0 ? (
                                <TableRow>
                                    <TableCell colSpan={5} className="py-12 text-center text-muted-foreground">
                                        <div className="flex flex-col items-center justify-center gap-2">
                                            <Users className="size-8 opacity-30" />
                                            <p className="text-sm font-medium">{t('admin.users.noUsersFound')}</p>
                                        </div>
                                    </TableCell>
                                </TableRow>
                            ) : (
                                users.map((user) => {
                                    const roleInfo = ROLE_BADGES[user.role_data?.code || 'GUEST'] || ROLE_BADGES['GUEST'];
                                    const company = user.company as Company | undefined;
                                    const isSelf = user.id === currentUser?.id;

                                    return (
                                        <TableRow key={user.id}>
                                            <TableCell>
                                                <div className="flex items-center gap-3">
                                                    <Avatar size="sm">
                                                        <AvatarFallback className="text-xs font-bold">
                                                            {user.email.substring(0, 2).toUpperCase()}
                                                        </AvatarFallback>
                                                    </Avatar>
                                                    <div className="min-w-0">
                                                        <div className="text-sm font-semibold truncate">
                                                            {user.first_name} {user.last_name}
                                                        </div>
                                                        <div className="text-xs text-muted-foreground truncate">
                                                            {user.email}
                                                        </div>
                                                    </div>
                                                </div>
                                            </TableCell>
                                            <TableCell>
                                                <Badge variant={roleInfo.variant} className="gap-1 text-xs">
                                                    <Shield className="size-3" />
                                                    {roleInfo.label}
                                                </Badge>
                                            </TableCell>
                                            <TableCell>
                                                {company ? (
                                                    <div className="min-w-0">
                                                        <div className="text-sm text-muted-foreground flex items-center gap-1.5">
                                                            <Briefcase className="size-3 opacity-50" />
                                                            <span className="truncate">{company.name}</span>
                                                        </div>
                                                        {user.workspace_role && (
                                                            <div className="text-xs text-muted-foreground mt-0.5 ml-[18px]">
                                                                {user.workspace_role}
                                                            </div>
                                                        )}
                                                    </div>
                                                ) : (
                                                    <span className="text-xs text-muted-foreground">{t('admin.users.internal')}</span>
                                                )}
                                            </TableCell>
                                            <TableCell>
                                                <div className="flex items-center gap-2">
                                                    <Switch
                                                        size="sm"
                                                        checked={user.is_active ?? false}
                                                        onCheckedChange={() => toggleStatus(user)}
                                                        disabled={isSelf}
                                                    />
                                                    <Badge
                                                        variant={user.is_active ? 'secondary' : 'destructive'}
                                                        className="text-xs"
                                                    >
                                                        {user.is_active ? t('common.active') : t('common.inactive')}
                                                    </Badge>
                                                </div>
                                            </TableCell>
                                            <TableCell className="text-right">
                                                <DropdownMenu>
                                                    <DropdownMenuTrigger asChild>
                                                        <Button variant="ghost" size="icon-xs">
                                                            <MoreHorizontal className="size-4" />
                                                            <span className="sr-only">{t('admin.users.columns.actions')}</span>
                                                        </Button>
                                                    </DropdownMenuTrigger>
                                                    <DropdownMenuContent align="end">
                                                        <DropdownMenuItem onClick={() => handleEditClick(user)}>
                                                            <Edit className="size-4" />
                                                            {t('admin.users.editUser')}
                                                        </DropdownMenuItem>
                                                        <DropdownMenuSeparator />
                                                        <DropdownMenuItem
                                                            variant="destructive"
                                                            disabled={isSelf}
                                                            onClick={() => setDeleteDialogUser(user)}
                                                        >
                                                            <Trash2 className="size-4" />
                                                            {t('admin.users.deleteUser')}
                                                        </DropdownMenuItem>
                                                    </DropdownMenuContent>
                                                </DropdownMenu>
                                            </TableCell>
                                        </TableRow>
                                    );
                                })
                            )}
                        </TableBody>
                    </Table>
                </div>
            </CardContent>

            {/* Delete Confirmation Dialog */}
            <Dialog open={!!deleteDialogUser} onOpenChange={(open) => !open && setDeleteDialogUser(null)}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>{t('admin.users.deleteUser')}</DialogTitle>
                        <DialogDescription>
                            {t('admin.users.deleteConfirmation', { email: deleteDialogUser?.email })}
                        </DialogDescription>
                    </DialogHeader>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setDeleteDialogUser(null)}>
                            {t('common.cancel')}
                        </Button>
                        <Button
                            variant="destructive"
                            onClick={handleDeleteUser}
                            disabled={deleteMutation.isPending}
                        >
                            {deleteMutation.isPending ? t('common.deleting') : t('common.delete')}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            <UserSlidePanel
                isOpen={isPanelOpen}
                onClose={() => setIsPanelOpen(false)}
                user={selectedUser}
                onSave={handleSavePanel}
            />
        </Card>
    );
};
