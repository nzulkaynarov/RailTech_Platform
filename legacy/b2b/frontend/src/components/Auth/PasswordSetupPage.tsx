import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useForm } from 'react-hook-form';
import { z } from 'zod';
import { zodResolver } from '@hookform/resolvers/zod';
import { Lock, CheckCircle, Loader2, AlertCircle } from 'lucide-react';
import { accountsApi } from '@/api/accountsApi';
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

interface PasswordSetupPageProps {
    uid: string | null;
    token: string | null;
    onLogin: () => void;
}

const createPasswordSetupSchema = (t: (key: string) => string) =>
    z
        .object({
            password: z.string().min(8, t('passwordSetup.validation.minLength')),
            confirmPassword: z.string().min(1, t('passwordSetup.validation.confirm')),
        })
        .refine((data) => data.password === data.confirmPassword, {
            message: t('passwordSetup.validation.mismatch'),
            path: ['confirmPassword'],
        });

type PasswordSetupFormData = z.infer<ReturnType<typeof createPasswordSetupSchema>>;

export const PasswordSetupPage: React.FC<PasswordSetupPageProps> = ({ uid, token, onLogin }) => {
    const { t } = useTranslation();

    const [loading, setLoading] = useState(false);
    const [serverError, setServerError] = useState('');
    const [success, setSuccess] = useState(false);

    const passwordSetupSchema = createPasswordSetupSchema(t);

    const form = useForm<PasswordSetupFormData>({
        resolver: zodResolver(passwordSetupSchema),
        defaultValues: {
            password: '',
            confirmPassword: '',
        },
    });

    useEffect(() => {
        if (!uid || !token) {
            setServerError(t('passwordSetup.invalidLink'));
        }
    }, [uid, token, t]);

    const onSubmit = async (data: PasswordSetupFormData) => {
        if (!uid || !token) {
            setServerError(t('passwordSetup.invalidLink'));
            return;
        }
        setLoading(true);
        setServerError('');
        try {
            await accountsApi.setupPassword({
                uid,
                token,
                password: data.password,
            });
            setSuccess(true);
        } catch (err: unknown) {
            const errorMessage =
                err instanceof Error
                    ? err.message
                    : t('passwordSetup.setupError');
            setServerError(errorMessage);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div data-testid="password-setup-page" className="min-h-screen bg-background flex items-center justify-center p-6 font-sans">
            <Card className="w-full max-w-md">
                <CardHeader>
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-xl bg-primary flex items-center justify-center">
                            <Lock className="w-5 h-5 text-primary-foreground" />
                        </div>
                        <div>
                            <CardTitle className="text-2xl font-black tracking-tight">
                                {t('passwordSetup.title')}
                            </CardTitle>
                            <CardDescription className="text-sm font-medium tracking-wide uppercase">
                                {t('passwordSetup.step')}
                            </CardDescription>
                        </div>
                    </div>
                </CardHeader>

                <CardContent>
                    {(!uid || !token) ? (
                        <div className="space-y-4">
                            <Alert variant="destructive">
                                <AlertCircle className="h-4 w-4" />
                                <AlertDescription>
                                    {t('passwordSetup.invalidLink')}
                                </AlertDescription>
                            </Alert>
                            <Button variant="outline" className="w-full" onClick={onLogin}>
                                {t('passwordSetup.goToLogin')}
                            </Button>
                        </div>
                    ) : !success ? (
                        <Form {...form}>
                            <form
                                onSubmit={form.handleSubmit(onSubmit)}
                                className="space-y-6"
                            >
                                <div className="space-y-4">
                                    <FormField
                                        control={form.control}
                                        name="password"
                                        render={({ field }) => (
                                            <FormItem>
                                                <FormLabel>
                                                    {t('passwordSetup.newPassword')}
                                                </FormLabel>
                                                <FormControl>
                                                    <Input
                                                        type="password"
                                                        placeholder={t('passwordSetup.newPasswordPlaceholder')}
                                                        {...field}
                                                    />
                                                </FormControl>
                                                <FormMessage />
                                            </FormItem>
                                        )}
                                    />

                                    <FormField
                                        control={form.control}
                                        name="confirmPassword"
                                        render={({ field }) => (
                                            <FormItem>
                                                <FormLabel>
                                                    {t('passwordSetup.confirmPassword')}
                                                </FormLabel>
                                                <FormControl>
                                                    <Input
                                                        type="password"
                                                        placeholder={t('passwordSetup.confirmPasswordPlaceholder')}
                                                        {...field}
                                                    />
                                                </FormControl>
                                                <FormMessage />
                                            </FormItem>
                                        )}
                                    />
                                </div>

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
                                    disabled={loading || !uid || !token}
                                    className="w-full"
                                    size="lg"
                                >
                                    {loading && (
                                        <Loader2 className="h-4 w-4 animate-spin" />
                                    )}
                                    {t('passwordSetup.submit')}
                                </Button>
                            </form>
                        </Form>
                    ) : (
                        <div className="text-center py-4">
                            <div className="w-20 h-20 bg-chart-2/20 rounded-full flex items-center justify-center mx-auto mb-6 border border-chart-2/30">
                                <CheckCircle className="w-10 h-10 text-chart-2" />
                            </div>
                            <h3 className="text-xl font-bold text-foreground mb-2">
                                {t('passwordSetup.success')}
                            </h3>
                            <p className="text-muted-foreground mb-8 text-sm">
                                {t('passwordSetup.successHint')}
                            </p>
                            <Button
                                onClick={onLogin}
                                className="w-full"
                                size="lg"
                            >
                                {t('passwordSetup.goToLogin')}
                            </Button>
                        </div>
                    )}
                </CardContent>
            </Card>
        </div>
    );
};
