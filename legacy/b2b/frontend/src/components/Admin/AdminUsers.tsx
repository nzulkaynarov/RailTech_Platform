import React, { useState } from 'react';
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
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';

const ROLE_BADGES: Record<string, { label: string; variant: 'default' | 'secondary' | 'destructive' | 'outline' }> = {
    'ADMIN': { label: 'SYS_ADMIN', variant: 'default' },
    'SALES_MANAGER': { label: 'SALES_OPS', variant: 'secondary' },
    'ACCOUNT_MANAGER': { label: 'ACC_EXEC', variant: 'secondary' },
    'CLIENT': { label: 'EXT_PARTNER', variant: 'outline' },
    'GUEST': { label: 'AUDIT_ONLY', variant: 'outline' },
};

export const AdminUsers: React.FC = () => {
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
            alert('Error: ' + (e.response?.data?.detail || e.message || 'Unknown error'));
        }
    };

    return (
        <Card className="h-full flex flex-col">
            <CardHeader className="border-b">
                <div className="flex items-center justify-between">
                    <div>
                        <CardTitle className="text-xl font-black tracking-tight uppercase">
                            Personnel <span className="text-primary">Registry</span>
                        </CardTitle>
                        <CardDescription className="text-xs font-bold uppercase tracking-widest mt-1">
                            System Access Control & Authorization Management
                        </CardDescription>
                    </div>
                    <Button size="sm" onClick={handleCreateClick}>
                        <Plus className="size-4" />
                        Provision User
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
                            placeholder="Search by name or email..."
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            className="pl-9"
                        />
                    </div>
                    <Select value={filterRole} onValueChange={setFilterRole}>
                        <SelectTrigger className="w-[180px]">
                            <SelectValue placeholder="Filter by role" />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="ALL">All Roles</SelectItem>
                            <SelectItem value="ADMIN">SYS_ADMIN</SelectItem>
                            <SelectItem value="SALES_MANAGER">SALES_OPS</SelectItem>
                            <SelectItem value="ACCOUNT_MANAGER">ACC_EXEC</SelectItem>
                            <SelectItem value="CLIENT">EXT_PARTNER</SelectItem>
                            <SelectItem value="GUEST">AUDIT_ONLY</SelectItem>
                        </SelectContent>
                    </Select>
                </div>

                {/* Data Table */}
                <div className="flex-1 overflow-auto rounded-md border">
                    <table className="w-full text-left border-collapse">
                        <thead className="sticky top-0 z-10 bg-muted text-muted-foreground text-xs font-semibold uppercase tracking-wider border-b">
                            <tr>
                                <th className="px-4 py-3">User</th>
                                <th className="px-4 py-3">Role</th>
                                <th className="px-4 py-3">Company</th>
                                <th className="px-4 py-3">Status</th>
                                <th className="px-4 py-3 text-right">Actions</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y">
                            {isLoading ? (
                                Array.from({ length: 5 }).map((_, i) => (
                                    <tr key={i}>
                                        <td className="px-4 py-3">
                                            <div className="flex items-center gap-3">
                                                <Skeleton className="size-8 rounded-full" />
                                                <div className="space-y-1.5">
                                                    <Skeleton className="h-3.5 w-28" />
                                                    <Skeleton className="h-3 w-40" />
                                                </div>
                                            </div>
                                        </td>
                                        <td className="px-4 py-3"><Skeleton className="h-5 w-20" /></td>
                                        <td className="px-4 py-3"><Skeleton className="h-3.5 w-24" /></td>
                                        <td className="px-4 py-3"><Skeleton className="h-5 w-10" /></td>
                                        <td className="px-4 py-3"><Skeleton className="h-8 w-8 ml-auto" /></td>
                                    </tr>
                                ))
                            ) : users.length === 0 ? (
                                <tr>
                                    <td colSpan={5} className="px-4 py-12 text-center text-muted-foreground">
                                        <div className="flex flex-col items-center justify-center gap-2">
                                            <Users className="size-8 opacity-30" />
                                            <p className="text-sm font-medium">No users found</p>
                                        </div>
                                    </td>
                                </tr>
                            ) : (
                                users.map((user) => {
                                    const roleInfo = ROLE_BADGES[user.role_data?.code || 'GUEST'] || ROLE_BADGES['GUEST'];
                                    const company = user.company as Company | undefined;
                                    const isSelf = user.id === currentUser?.id;

                                    return (
                                        <tr key={user.id} className="hover:bg-muted/50 transition-colors">
                                            <td className="px-4 py-3">
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
                                            </td>
                                            <td className="px-4 py-3">
                                                <Badge variant={roleInfo.variant} className="gap-1 text-xs">
                                                    <Shield className="size-3" />
                                                    {roleInfo.label}
                                                </Badge>
                                            </td>
                                            <td className="px-4 py-3">
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
                                                    <span className="text-xs text-muted-foreground">Internal</span>
                                                )}
                                            </td>
                                            <td className="px-4 py-3">
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
                                                        {user.is_active ? 'Active' : 'Inactive'}
                                                    </Badge>
                                                </div>
                                            </td>
                                            <td className="px-4 py-3 text-right">
                                                <DropdownMenu>
                                                    <DropdownMenuTrigger asChild>
                                                        <Button variant="ghost" size="icon-xs">
                                                            <MoreHorizontal className="size-4" />
                                                            <span className="sr-only">Actions</span>
                                                        </Button>
                                                    </DropdownMenuTrigger>
                                                    <DropdownMenuContent align="end">
                                                        <DropdownMenuItem onClick={() => handleEditClick(user)}>
                                                            <Edit className="size-4" />
                                                            Edit User
                                                        </DropdownMenuItem>
                                                        <DropdownMenuSeparator />
                                                        <DropdownMenuItem
                                                            variant="destructive"
                                                            disabled={isSelf}
                                                            onClick={() => setDeleteDialogUser(user)}
                                                        >
                                                            <Trash2 className="size-4" />
                                                            Delete User
                                                        </DropdownMenuItem>
                                                    </DropdownMenuContent>
                                                </DropdownMenu>
                                            </td>
                                        </tr>
                                    );
                                })
                            )}
                        </tbody>
                    </table>
                </div>
            </CardContent>

            {/* Delete Confirmation Dialog */}
            <Dialog open={!!deleteDialogUser} onOpenChange={(open) => !open && setDeleteDialogUser(null)}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Delete User</DialogTitle>
                        <DialogDescription>
                            Are you sure you want to permanently delete{' '}
                            <span className="font-semibold">{deleteDialogUser?.email}</span>?
                            This action cannot be undone.
                        </DialogDescription>
                    </DialogHeader>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setDeleteDialogUser(null)}>
                            Cancel
                        </Button>
                        <Button
                            variant="destructive"
                            onClick={handleDeleteUser}
                            disabled={deleteMutation.isPending}
                        >
                            {deleteMutation.isPending ? 'Deleting...' : 'Delete'}
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
