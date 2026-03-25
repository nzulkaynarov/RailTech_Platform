import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Loader2, AlertCircle } from 'lucide-react';
import { accountsApi } from '@/api/accountsApi';
import { useAuthStore } from '@/store/authStore';
import {
    Card,
    CardHeader,
    CardTitle,
    CardDescription,
    CardContent,
} from '@/components/ui/card';
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
import { Alert, AlertDescription } from '@/components/ui/alert';

const profileSchema = z.object({
    companyName: z.string().min(2, 'Минимум 2 символа'),
    inn: z.string().regex(/^\d{9}$/, 'ИНН должен содержать ровно 9 цифр'),
    role: z.enum(['OWNER', 'MANAGER', 'ACCOUNTANT'], {
        message: 'Выберите роль',
    }),
});

type ProfileFormValues = z.infer<typeof profileSchema>;

export const ProfileCompletionForm: React.FC = () => {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const { initAuth } = useAuthStore();
    const [serverError, setServerError] = useState('');

    const form = useForm<ProfileFormValues>({
        resolver: zodResolver(profileSchema),
        defaultValues: {
            companyName: '',
            inn: '',
            role: 'OWNER',
        },
    });

    const onSubmit = async (data: ProfileFormValues) => {
        setServerError('');
        try {
            await accountsApi.submitProfile(data);
            await initAuth();
            navigate('/cabinet/home');
        } catch (err: unknown) {
            const errorMessage =
                err instanceof Error
                    ? err.message
                    : t('profileForm.saveError');
            setServerError(errorMessage);
        }
    };

    return (
        <div className="min-h-screen bg-background flex items-center justify-center p-6 relative overflow-hidden font-sans">
            <div className="absolute top-0 right-0 w-96 h-96 bg-primary/20 blur-[100px] rounded-full" />
            <div className="absolute bottom-0 left-0 w-80 h-80 bg-chart-2/10 blur-[80px] rounded-full" />

            <Card className="relative z-10 w-full max-w-xl border-border bg-card text-card-foreground shadow-2xl">
                <CardHeader>
                    <CardTitle className="text-2xl font-black tracking-tight">
                        {t('profileForm.title')}
                    </CardTitle>
                    <CardDescription>
                        {t('profileForm.step')}
                    </CardDescription>
                </CardHeader>

                <CardContent>
                    <Form {...form}>
                        <form
                            onSubmit={form.handleSubmit(onSubmit)}
                            className="space-y-6"
                        >
                            <FormField
                                control={form.control}
                                name="companyName"
                                render={({ field }) => (
                                    <FormItem>
                                        <FormLabel>
                                            {t('profileForm.companyName')}
                                        </FormLabel>
                                        <FormControl>
                                            <Input
                                                placeholder={t('profileForm.companyNamePlaceholder')}
                                                {...field}
                                            />
                                        </FormControl>
                                        <FormMessage />
                                    </FormItem>
                                )}
                            />

                            <FormField
                                control={form.control}
                                name="inn"
                                render={({ field }) => (
                                    <FormItem>
                                        <FormLabel>{t('profileForm.innLabel')}</FormLabel>
                                        <FormControl>
                                            <Input
                                                placeholder={t('profileForm.innPlaceholder')}
                                                {...field}
                                            />
                                        </FormControl>
                                        <FormMessage />
                                    </FormItem>
                                )}
                            />

                            <FormField
                                control={form.control}
                                name="role"
                                render={({ field }) => (
                                    <FormItem>
                                        <FormLabel>
                                            {t('profileForm.roleLabel')}
                                        </FormLabel>
                                        <Select
                                            onValueChange={field.onChange}
                                            defaultValue={field.value}
                                        >
                                            <FormControl>
                                                <SelectTrigger className="w-full">
                                                    <SelectValue placeholder={t('profileForm.rolePlaceholder')} />
                                                </SelectTrigger>
                                            </FormControl>
                                            <SelectContent>
                                                <SelectItem value="OWNER">
                                                    {t('profileForm.roleOwner')}
                                                </SelectItem>
                                                <SelectItem value="MANAGER">
                                                    {t('profileForm.roleManager')}
                                                </SelectItem>
                                                <SelectItem value="ACCOUNTANT">
                                                    {t('profileForm.roleAccountant')}
                                                </SelectItem>
                                            </SelectContent>
                                        </Select>
                                        <FormMessage />
                                    </FormItem>
                                )}
                            />

                            {serverError && (
                                <Alert variant="destructive">
                                    <AlertCircle className="h-4 w-4" />
                                    <AlertDescription>
                                        {serverError}
                                    </AlertDescription>
                                </Alert>
                            )}

                            <Button
                                type="submit"
                                className="w-full"
                                size="lg"
                                disabled={form.formState.isSubmitting}
                            >
                                {form.formState.isSubmitting && (
                                    <Loader2 className="h-4 w-4 animate-spin" />
                                )}
                                {t('profileForm.submit')}
                            </Button>
                        </form>
                    </Form>
                </CardContent>
            </Card>
        </div>
    );
};
