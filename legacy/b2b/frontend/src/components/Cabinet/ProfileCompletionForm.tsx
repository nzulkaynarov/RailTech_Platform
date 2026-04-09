import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Loader2, AlertCircle, ShoppingCart, Factory, Store, Building2, Check } from 'lucide-react';
import { accountsApi } from '@/api/accountsApi';
import { useAuthStore } from '@/store/authStore';
import { cn } from '@/lib/utils';

import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Form, FormField, FormItem, FormLabel, FormControl, FormMessage } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Separator } from '@/components/ui/separator';

const COMPANY_TYPES = [
    { code: 'CLIENT', icon: ShoppingCart, labelKey: 'profileForm.typeBuyer', descKey: 'profileForm.typeBuyerDesc' },
    { code: 'MANUFACTURER', icon: Factory, labelKey: 'profileForm.typeManufacturer', descKey: 'profileForm.typeManufacturerDesc' },
    { code: 'SUPPLIER', icon: Store, labelKey: 'profileForm.typeSupplier', descKey: 'profileForm.typeSupplierDesc' },
] as const;

const createProfileSchema = (t: (key: string) => string) => z.object({
    companyName: z.string().min(2, t('profileForm.validation.minChars')),
    inn: z.string().regex(/^\d{9}$/, t('profileForm.validation.innFormat')),
    company_type: z.string().min(1, t('profileForm.validation.selectType')),
});

type ProfileFormValues = z.infer<ReturnType<typeof createProfileSchema>>;

interface ProfileCompletionFormProps {
    onComplete: () => void;
}

export const ProfileCompletionForm: React.FC<ProfileCompletionFormProps> = ({ onComplete }) => {
    const { t } = useTranslation();
    const { initAuth } = useAuthStore();
    const [serverError, setServerError] = useState('');
    const profileSchema = useMemo(() => createProfileSchema(t), [t]);

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
                err instanceof Error ? err.message : t('profileForm.saveError');
            setServerError(errorMessage);
        }
    };

    return (
        <div className="min-h-screen bg-background flex items-center justify-center p-6">
            <Card className="w-full max-w-2xl">
                <CardHeader className="text-center">
                    <div className="mx-auto mb-2 flex h-14 w-14 items-center justify-center rounded-full bg-muted">
                        <Building2 className="h-7 w-7 text-muted-foreground" />
                    </div>
                    <CardTitle className="text-xl">{t('profileForm.title')}</CardTitle>
                    <CardDescription>{t('profileForm.step')}</CardDescription>
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
                                                <Button
                                                    key={code}
                                                    type="button"
                                                    variant="ghost"
                                                    onClick={() => field.onChange(code)}
                                                    className={cn(
                                                        'relative flex flex-col items-center rounded-lg border-2 p-4 text-center transition-all h-auto',
                                                        selectedType === code
                                                            ? 'border-primary bg-primary/5'
                                                            : 'border-border hover:border-muted-foreground/30'
                                                    )}
                                                >
                                                    {selectedType === code && (
                                                        <div className="absolute right-2 top-2 flex h-5 w-5 items-center justify-center rounded-full bg-primary text-primary-foreground">
                                                            <Check className="h-3 w-3" />
                                                        </div>
                                                    )}
                                                    <div className={cn(
                                                        'flex h-10 w-10 items-center justify-center rounded-lg',
                                                        selectedType === code ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground'
                                                    )}>
                                                        <Icon className="h-5 w-5" />
                                                    </div>
                                                    <h3 className="mt-2 text-sm font-semibold">{t(labelKey)}</h3>
                                                    <p className="mt-1 text-xs text-muted-foreground">{t(descKey)}</p>
                                                </Button>
                                            ))}
                                        </div>
                                        <FormMessage />
                                    </FormItem>
                                )}
                            />

                            <Separator />

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
                                {form.formState.isSubmitting && <Loader2 className="h-4 w-4 animate-spin" />}
                                {t('profileForm.submit')}
                            </Button>
                        </form>
                    </Form>
                </CardContent>
            </Card>
        </div>
    );
};
