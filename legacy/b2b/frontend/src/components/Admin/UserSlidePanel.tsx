import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useForm } from 'react-hook-form';
import { z } from 'zod';
import { zodResolver } from '@hookform/resolvers/zod';
import { Loader2 } from 'lucide-react';

import { User as UserType, Company } from '@/api/accountsApi';

import {
    Sheet,
    SheetContent,
    SheetHeader,
    SheetTitle,
    SheetDescription,
    SheetFooter,
} from '@/components/ui/sheet';
import {
    Form,
    FormField,
    FormItem,
    FormLabel,
    FormControl,
    FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import {
    Select,
    SelectTrigger,
    SelectValue,
    SelectContent,
    SelectItem,
} from '@/components/ui/select';
import { Button } from '@/components/ui/button';
import { useCompanies } from '@/hooks/useAccounts';

// ---------------------------------------------------------------------------
// Zod schema factory
// ---------------------------------------------------------------------------
const createUserFormSchema = (t: (key: string, options?: any) => string) =>
    z.object({
        email: z.string().email(t('validation.validEmailRequired')),
        first_name: z.string().min(1, t('validation.firstNameRequired')),
        last_name: z.string().min(1, t('validation.lastNameRequired')),
        role: z.enum(['ADMIN', 'SALES_MANAGER', 'ACCOUNT_MANAGER', 'CLIENT']),
        company_id: z.string().optional(),
        workspace_role: z.enum(['OWNER', 'ACCOUNTANT', 'MANAGER', '']).optional(),
    });

type UserFormValues = z.infer<ReturnType<typeof createUserFormSchema>>;

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------
interface UserSlidePanelProps {
    isOpen: boolean;
    onClose: () => void;
    user: UserType | null;
    onSave: (data: Partial<UserType>) => Promise<void>;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export const UserSlidePanel: React.FC<UserSlidePanelProps> = ({
    isOpen,
    onClose,
    user,
    onSave,
}) => {
    const { t } = useTranslation();
    const isEdit = !!user;

    const userFormSchema = createUserFormSchema(t);

    const { data: companies = [] } = useCompanies();

    const form = useForm<UserFormValues>({
        resolver: zodResolver(userFormSchema),
        defaultValues: {
            email: '',
            first_name: '',
            last_name: '',
            role: 'CLIENT',
            company_id: '',
            workspace_role: '',
        },
    });

    // Reset form values when user prop changes or panel opens
    useEffect(() => {
        if (isOpen) {
            form.reset({
                email: user?.email ?? '',
                first_name: user?.first_name ?? '',
                last_name: user?.last_name ?? '',
                role: (user?.role as UserFormValues['role']) ?? 'CLIENT',
                company_id: user?.company?.id?.toString() ?? '',
                workspace_role:
                    (user?.workspace_role as UserFormValues['workspace_role']) ?? '',
            });
        }
    }, [user, isOpen, form]);

    const handleSubmit = async (values: UserFormValues) => {
        const payload: Partial<UserType> = {
            email: values.email,
            first_name: values.first_name,
            last_name: values.last_name,
            role: values.role,
            company_id: values.company_id ? parseInt(values.company_id, 10) : null,
            workspace_role: values.workspace_role || null,
        };

        try {
            await onSave(payload);
            onClose();
        } catch (error) {
            console.error('Save failed', error);
        }
    };

    const watchedRole = form.watch('role');

    return (
        <Sheet open={isOpen} onOpenChange={(open) => !open && onClose()}>
            <SheetContent side="right" className="w-full sm:max-w-[440px] flex flex-col p-0">
                <SheetHeader className="px-6 py-4 border-b">
                    <SheetTitle>
                        {isEdit ? t('userPanel.editTitle') : t('userPanel.createTitle')}
                    </SheetTitle>
                    <SheetDescription>
                        {isEdit
                            ? t('userPanel.editDescription', { id: user.id })
                            : t('userPanel.createDescription')}
                    </SheetDescription>
                </SheetHeader>

                <div className="flex-1 overflow-y-auto px-6 py-6">
                    <Form {...form}>
                        <form
                            id="user-form"
                            onSubmit={form.handleSubmit(handleSubmit)}
                            className="space-y-5"
                        >
                            {/* --- Identity fields --- */}
                            <div className="grid grid-cols-2 gap-4">
                                <FormField
                                    control={form.control}
                                    name="first_name"
                                    render={({ field }) => (
                                        <FormItem>
                                            <FormLabel>{t('userPanel.firstName')}</FormLabel>
                                            <FormControl>
                                                <Input
                                                    placeholder={t('userPanel.firstNamePlaceholder')}
                                                    {...field}
                                                />
                                            </FormControl>
                                            <FormMessage />
                                        </FormItem>
                                    )}
                                />

                                <FormField
                                    control={form.control}
                                    name="last_name"
                                    render={({ field }) => (
                                        <FormItem>
                                            <FormLabel>{t('userPanel.lastName')}</FormLabel>
                                            <FormControl>
                                                <Input
                                                    placeholder={t('userPanel.lastNamePlaceholder')}
                                                    {...field}
                                                />
                                            </FormControl>
                                            <FormMessage />
                                        </FormItem>
                                    )}
                                />
                            </div>

                            <FormField
                                control={form.control}
                                name="email"
                                render={({ field }) => (
                                    <FormItem>
                                        <FormLabel>{t('userPanel.email')}</FormLabel>
                                        <FormControl>
                                            <Input
                                                type="email"
                                                placeholder={t('userPanel.emailPlaceholder')}
                                                disabled={isEdit}
                                                {...field}
                                            />
                                        </FormControl>
                                        <FormMessage />
                                    </FormItem>
                                )}
                            />

                            {/* --- Role --- */}
                            <FormField
                                control={form.control}
                                name="role"
                                render={({ field }) => (
                                    <FormItem>
                                        <FormLabel>{t('userPanel.role')}</FormLabel>
                                        <Select
                                            onValueChange={field.onChange}
                                            value={field.value}
                                        >
                                            <FormControl>
                                                <SelectTrigger className="w-full">
                                                    <SelectValue placeholder={t('userPanel.rolePlaceholder')} />
                                                </SelectTrigger>
                                            </FormControl>
                                            <SelectContent>
                                                <SelectItem value="ADMIN">
                                                    {t('userPanel.roleAdmin')}
                                                </SelectItem>
                                                <SelectItem value="SALES_MANAGER">
                                                    {t('userPanel.roleSalesManager')}
                                                </SelectItem>
                                                <SelectItem value="ACCOUNT_MANAGER">
                                                    {t('userPanel.roleAccountManager')}
                                                </SelectItem>
                                                <SelectItem value="CLIENT">
                                                    {t('userPanel.roleClient')}
                                                </SelectItem>
                                            </SelectContent>
                                        </Select>
                                        <FormMessage />
                                    </FormItem>
                                )}
                            />

                            {/* --- Company --- */}
                            <FormField
                                control={form.control}
                                name="company_id"
                                render={({ field }) => (
                                    <FormItem>
                                        <FormLabel>{t('userPanel.company')}</FormLabel>
                                        <Select
                                            onValueChange={field.onChange}
                                            value={field.value}
                                        >
                                            <FormControl>
                                                <SelectTrigger className="w-full">
                                                    <SelectValue placeholder={t('userPanel.companyPlaceholder')} />
                                                </SelectTrigger>
                                            </FormControl>
                                            <SelectContent>
                                                <SelectItem value="">
                                                    {t('userPanel.internalStaff')}
                                                </SelectItem>
                                                {companies.map((c: Company) => (
                                                    <SelectItem
                                                        key={c.id}
                                                        value={c.id.toString()}
                                                    >
                                                        {c.name} (VAT: {c.inn})
                                                    </SelectItem>
                                                ))}
                                            </SelectContent>
                                        </Select>
                                        <FormMessage />
                                    </FormItem>
                                )}
                            />

                            {/* --- Workspace role (only for CLIENT) --- */}
                            {watchedRole === 'CLIENT' && (
                                <FormField
                                    control={form.control}
                                    name="workspace_role"
                                    render={({ field }) => (
                                        <FormItem>
                                            <FormLabel>{t('userPanel.workspaceRole')}</FormLabel>
                                            <Select
                                                onValueChange={field.onChange}
                                                value={field.value}
                                            >
                                                <FormControl>
                                                    <SelectTrigger className="w-full">
                                                        <SelectValue placeholder={t('userPanel.workspaceRolePlaceholder')} />
                                                    </SelectTrigger>
                                                </FormControl>
                                                <SelectContent>
                                                    <SelectItem value="">
                                                        {t('userPanel.workspaceNone')}
                                                    </SelectItem>
                                                    <SelectItem value="OWNER">
                                                        {t('userPanel.workspaceOwner')}
                                                    </SelectItem>
                                                    <SelectItem value="ACCOUNTANT">
                                                        {t('userPanel.workspaceAccountant')}
                                                    </SelectItem>
                                                    <SelectItem value="MANAGER">
                                                        {t('userPanel.workspaceManager')}
                                                    </SelectItem>
                                                </SelectContent>
                                            </Select>
                                            <FormMessage />
                                        </FormItem>
                                    )}
                                />
                            )}
                        </form>
                    </Form>
                </div>

                <SheetFooter className="border-t px-6 py-4 flex-row justify-end gap-2">
                    <Button
                        type="button"
                        variant="outline"
                        onClick={onClose}
                    >
                        {t('common.cancel')}
                    </Button>
                    <Button
                        type="submit"
                        form="user-form"
                        disabled={form.formState.isSubmitting}
                    >
                        {form.formState.isSubmitting ? (
                            <Loader2 className="size-4 animate-spin" />
                        ) : isEdit ? (
                            t('common.update')
                        ) : (
                            t('common.add')
                        )}
                    </Button>
                </SheetFooter>
            </SheetContent>
        </Sheet>
    );
};
