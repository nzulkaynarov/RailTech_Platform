import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Loader2, AlertCircle, Building2 } from 'lucide-react';
import { accountsApi } from '@/api/accountsApi';
import { translateApiError } from '@/lib/apiError';
import { useAuthStore } from '@/store/authStore';

import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Form, FormField, FormItem, FormLabel, FormControl, FormMessage } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';

const createProfileSchema = (t: (key: string) => string) =>
    z.object({
        companyName: z.string().min(2, t('profileForm.validation.minChars')),
        position: z.string().min(2, t('profileForm.validation.positionRequired')),
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
            position: '',
        },
    });

    const onSubmit = async (data: ProfileFormValues) => {
        setServerError('');
        try {
            // CRM Phase D — a CB-invite token (stashed from /register?invite=…) claims the
            // existing offline company instead of creating a new one. Cleared after a successful
            // claim so a later manual company creation isn't mis-attached.
            const invite = sessionStorage.getItem('cb_invite_token') || undefined;
            await accountsApi.submitProfile({
                companyName: data.companyName,
                position: data.position,
                invite,
            });
            sessionStorage.removeItem('cb_invite_token');
            await initAuth();
            onComplete();
        } catch (err: unknown) {
            // translateApiError maps backend codes via the apiErrors namespace;
            // falls back to the raw code, then a generic message.
            setServerError(translateApiError(err) || t('profileForm.saveError'));
        }
    };

    return (
        <div className="min-h-screen bg-background flex items-center justify-center p-6">
            <Card className="w-full max-w-xl">
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

                            {/* Position / job title */}
                            <FormField
                                control={form.control}
                                name="position"
                                render={({ field }) => (
                                    <FormItem>
                                        <FormLabel>{t('profileForm.positionLabel')}</FormLabel>
                                        <FormControl>
                                            <Input placeholder={t('profileForm.positionPlaceholder')} {...field} />
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
