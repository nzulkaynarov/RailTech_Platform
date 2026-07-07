import { useEffect, useState } from 'react';
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

interface ResetPasswordPageProps {
    uid: string | null;
    token: string | null;
    onLogin: () => void;
    onForgot: () => void;
}

const createSchema = (t: (key: string) => string) =>
    z.object({
        password: z.string().min(8, t('passwordSetup.validation.minLength')),
        confirmPassword: z.string().min(1, t('passwordSetup.validation.confirm')),
    }).refine((d) => d.password === d.confirmPassword, {
        message: t('passwordSetup.validation.mismatch'),
        path: ['confirmPassword'],
    });

type FormData = z.infer<ReturnType<typeof createSchema>>;

export const ResetPasswordPage: React.FC<ResetPasswordPageProps> = ({ uid, token, onLogin, onForgot }) => {
    const { t } = useTranslation();
    const [loading, setLoading] = useState(false);
    const [serverError, setServerError] = useState('');
    const [success, setSuccess] = useState(false);
    const form = useForm<FormData>({
        resolver: zodResolver(createSchema(t)),
        defaultValues: { password: '', confirmPassword: '' },
    });

    useEffect(() => {
        if (!uid || !token) setServerError(t('resetPassword.invalidLink'));
    }, [uid, token, t]);

    const onSubmit = async (data: FormData) => {
        if (!uid || !token) {
            setServerError(t('resetPassword.invalidLink'));
            return;
        }
        setLoading(true);
        setServerError('');
        try {
            await accountsApi.resetPassword({
                uid,
                token,
                password: data.password,
            });
            setSuccess(true);
        } catch (err: unknown) {
            type AxiosLike = { response?: { data?: { detail?: string; error?: string } } };
            const code =
                (err as AxiosLike)?.response?.data?.detail ||
                (err as AxiosLike)?.response?.data?.error ||
                '';
            const map: Record<string, string> = {
                RESET_PASSWORD_INVALID_USER: t('resetPassword.invalidUser'),
                RESET_PASSWORD_INVALID_TOKEN: t('resetPassword.invalidToken'),
                RESET_PASSWORD_WEAK: t('resetPassword.weak'),
            };
            setServerError(map[code] ?? (code || t('resetPassword.genericError')));
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="min-h-screen bg-background flex items-center justify-center p-6 font-sans">
            <Card className="w-full max-w-md">
                <CardHeader>
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-xl bg-primary flex items-center justify-center">
                            <Lock className="w-5 h-5 text-primary-foreground" />
                        </div>
                        <div>
                            <CardTitle className="text-2xl font-black tracking-tight">
                                {t('resetPassword.title')}
                            </CardTitle>
                            <CardDescription className="text-sm font-medium tracking-wide uppercase">
                                {t('resetPassword.step')}
                            </CardDescription>
                        </div>
                    </div>
                </CardHeader>
                <CardContent>
                    {(!uid || !token) ? (
                        <div className="space-y-4">
                            <Alert variant="destructive">
                                <AlertCircle className="h-4 w-4" />
                                <AlertDescription>{t('resetPassword.invalidLink')}</AlertDescription>
                            </Alert>
                            <div className="flex gap-2">
                                <Button variant="outline" className="flex-1" onClick={onForgot}>
                                    {t('resetPassword.requestNew')}
                                </Button>
                                <Button className="flex-1" onClick={onLogin}>
                                    {t('passwordSetup.goToLogin')}
                                </Button>
                            </div>
                        </div>
                    ) : success ? (
                        <div className="space-y-4 text-center py-2">
                            <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-success/15">
                                <CheckCircle className="h-8 w-8 text-success" aria-hidden="true" />
                            </div>
                            <h3 className="text-lg font-semibold">{t('resetPassword.success')}</h3>
                            <p className="text-xs text-muted-foreground">
                                {t('resetPassword.successHint')}
                            </p>
                            <Button className="w-full" onClick={onLogin}>
                                {t('passwordSetup.goToLogin')}
                            </Button>
                        </div>
                    ) : (
                        <Form {...form}>
                            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
                                <FormField
                                    control={form.control}
                                    name="password"
                                    render={({ field }) => (
                                        <FormItem>
                                            <FormLabel>{t('passwordSetup.newPassword')}</FormLabel>
                                            <FormControl>
                                                <Input
                                                    type="password"
                                                    autoComplete="new-password"
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
                                            <FormLabel>{t('passwordSetup.confirmPassword')}</FormLabel>
                                            <FormControl>
                                                <Input
                                                    type="password"
                                                    autoComplete="new-password"
                                                    placeholder={t('passwordSetup.confirmPasswordPlaceholder')}
                                                    {...field}
                                                />
                                            </FormControl>
                                            <FormMessage />
                                        </FormItem>
                                    )}
                                />
                                {serverError ? (
                                    <Alert variant="destructive">
                                        <AlertCircle className="h-4 w-4" />
                                        <AlertDescription>{serverError}</AlertDescription>
                                    </Alert>
                                ) : null}
                                <Button type="submit" disabled={loading} className="w-full" size="lg">
                                    {loading ? (
                                        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                                    ) : null}
                                    {t('resetPassword.submit')}
                                </Button>
                            </form>
                        </Form>
                    )}
                </CardContent>
            </Card>
        </div>
    );
};

export default ResetPasswordPage;
