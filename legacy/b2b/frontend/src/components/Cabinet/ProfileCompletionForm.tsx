import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Loader2, AlertCircle, ShoppingCart, Factory, Store, Building2 } from 'lucide-react';
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
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { cn } from '@/lib/utils';

const COMPANY_TYPES = [
    { code: 'CLIENT', icon: ShoppingCart, labelKey: 'profileForm.typeBuyer', descKey: 'profileForm.typeBuyerDesc' },
    { code: 'MANUFACTURER', icon: Factory, labelKey: 'profileForm.typeManufacturer', descKey: 'profileForm.typeManufacturerDesc' },
    { code: 'SUPPLIER', icon: Store, labelKey: 'profileForm.typeSupplier', descKey: 'profileForm.typeSupplierDesc' },
] as const;

const profileSchema = z.object({
    companyName: z.string().min(2, 'Минимум 2 символа'),
    inn: z.string().regex(/^\d{9}$/, 'ИНН должен содержать ровно 9 цифр'),
    company_type: z.string().min(1, 'Выберите тип компании'),
});

type ProfileFormValues = z.infer<typeof profileSchema>;

interface ProfileCompletionFormProps {
    onComplete: () => void;
}

export const ProfileCompletionForm: React.FC<ProfileCompletionFormProps> = ({ onComplete }) => {
    const { t } = useTranslation();
    const { initAuth } = useAuthStore();
    const [serverError, setServerError] = useState('');

    const form = useForm<ProfileFormValues>({
        resolver: zodResolver(profileSchema),
        defaultValues: {
            companyName: '',
            inn: '',
            company_type: '',
        },
    });

    const selectedType = form.watch('company_type');

    const onSubmit = async (data: ProfileFormValues) => {
        setServerError('');
        try {
            await accountsApi.submitProfile({
                inn: data.inn,
                companyName: data.companyName,
                role: 'OWNER',
                company_type: data.company_type,
            });
            await initAuth();
            onComplete();
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

            <Card className="relative z-10 w-full max-w-2xl border-border bg-card text-card-foreground shadow-2xl">
                <CardHeader className="text-center">
                    <div className="mx-auto mb-2 flex h-14 w-14 items-center justify-center rounded-full bg-primary/10">
                        <Building2 className="h-7 w-7 text-primary" />
                    </div>
                    <CardTitle className="text-2xl font-black tracking-tight">
                        {t('profileForm.title')}
                    </CardTitle>
                    <CardDescription>
                        {t('profileForm.step')}
                    </CardDescription>
                </CardHeader>

                <CardContent>
                    <Form {...form}>
                        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
                            {/* Company type selection */}
                            <FormField
                                control={form.control}
                                name="company_type"
                                render={({ field }) => (
                                    <FormItem>
                                        <FormLabel>{t('profileForm.companyTypeLabel')}</FormLabel>
                                        <div className="grid gap-3 md:grid-cols-3">
                                            {COMPANY_TYPES.map(({ code, icon: Icon, labelKey, descKey }) => (
                                                <button
                                                    key={code}
                                                    type="button"
                                                    onClick={() => field.onChange(code)}
                                                    className={cn(
                                                        'flex flex-col items-center rounded-xl border-2 p-4 text-center transition-all hover:shadow-md',
                                                        selectedType === code
                                                            ? 'border-primary bg-primary/5 text-primary'
                                                            : 'border-border bg-card text-foreground hover:border-muted-foreground/30'
                                                    )}
                                                >
                                                    <div className={cn(
                                                        'flex h-10 w-10 items-center justify-center rounded-lg',
                                                        selectedType === code ? 'bg-primary/10' : 'bg-muted'
                                                    )}>
                                                        <Icon className="h-5 w-5" />
                                                    </div>
                                                    <h3 className="mt-2 text-sm font-bold">{t(labelKey)}</h3>
                                                    <p className={cn('mt-1 text-xs leading-snug', selectedType === code ? 'opacity-80' : 'text-muted-foreground')}>
                                                        {t(descKey)}
                                                    </p>
                                                </button>
                                            ))}
                                        </div>
                                        <FormMessage />
                                    </FormItem>
                                )}
                            />

                            {/* Company name */}
                            <FormField
                                control={form.control}
                                name="companyName"
                                render={({ field }) => (
                                    <FormItem>
                                        <FormLabel>{t('profileForm.companyName')}</FormLabel>
                                        <FormControl>
                                            <Input placeholder={t('profileForm.companyNamePlaceholder')} {...field} />
                                        </FormControl>
                                        <FormMessage />
                                    </FormItem>
                                )}
                            />

                            {/* INN */}
                            <FormField
                                control={form.control}
                                name="inn"
                                render={({ field }) => (
                                    <FormItem>
                                        <FormLabel>{t('profileForm.innLabel')}</FormLabel>
                                        <FormControl>
                                            <Input placeholder={t('profileForm.innPlaceholder')} {...field} />
                                        </FormControl>
                                        <FormMessage />
                                    </FormItem>
                                )}
                            />

                            {serverError && (
                                <Alert variant="destructive">
                                    <AlertCircle className="h-4 w-4" />
                                    <AlertDescription>{serverError}</AlertDescription>
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
