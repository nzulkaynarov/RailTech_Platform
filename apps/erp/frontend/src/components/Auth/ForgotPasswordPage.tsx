import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useForm } from 'react-hook-form';
import { z } from 'zod';
import { zodResolver } from '@hookform/resolvers/zod';
import { Mail, CheckCircle, Loader2, AlertCircle, ChevronLeft } from 'lucide-react';
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

interface ForgotPasswordPageProps {
    onLogin: () => void;
}

const createSchema = (t: (key: string) => string) =>
    z.object({
        email: z.string().email(t('auth.validation.emailInvalid')),
    });

type FormData = z.infer<ReturnType<typeof createSchema>>;

export const ForgotPasswordPage: React.FC<ForgotPasswordPageProps> = ({ onLogin }) => {
    const { t } = useTranslation();
    const [loading, setLoading] = useState(false);
    const [serverError, setServerError] = useState('');
    const [sent, setSent] = useState<string | null>(null);

    const form = useForm<FormData>({
        resolver: zodResolver(createSchema(t)),
        defaultValues: { email: '' },
    });

    const onSubmit = async (data: FormData) => {
        setLoading(true);
        setServerError('');
        try {
            await accountsApi.forgotPassword(data.email);
            setSent(data.email);
        } catch (err: unknown) {
            type AxiosLike = { response?: { data?: { detail?: string; error?: string } } };
            const detail =
                (err as AxiosLike)?.response?.data?.detail ||
                (err as AxiosLike)?.response?.data?.error ||
                (err instanceof Error ? err.message : '') ||
                t('forgotPassword.genericError');
            setServerError(detail);
        } finally {
            setLoading(false);
        }
    };

    async function handleResend() {
        if (!sent) return;
        setLoading(true);
        try {
            await accountsApi.forgotPassword(sent);
        } finally {
            setLoading(false);
        }
    }

    return (
        <div className="min-h-screen bg-background flex items-center justify-center p-6 font-sans">
            <Card className="w-full max-w-md">
                <CardHeader>
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-xl bg-primary flex items-center justify-center">
                            <Mail className="w-5 h-5 text-primary-foreground" />
                        </div>
                        <div>
                            <CardTitle className="text-2xl font-black tracking-tight">
                                {t('forgotPassword.title')}
                            </CardTitle>
                            <CardDescription className="text-sm font-medium tracking-wide uppercase">
                                {t('forgotPassword.step')}
                            </CardDescription>
                        </div>
                    </div>
                </CardHeader>
                <CardContent>
                    {sent ? (
                        <div className="space-y-4">
                            <div className="flex items-center gap-2 rounded-md border border-success/40 bg-success/5 p-3 text-sm">
                                <CheckCircle className="h-4 w-4 text-success" aria-hidden="true" />
                                <span>
                                    {t('forgotPassword.sent', { email: sent })}
                                </span>
                            </div>
                            <p className="text-xs text-muted-foreground">
                                {t('forgotPassword.sentHint')}
                            </p>
                            <div className="flex gap-2">
                                <Button
                                    variant="outline"
                                    className="flex-1"
                                    disabled={loading}
                                    onClick={handleResend}
                                >
                                    {loading ? (
                                        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                                    ) : null}
                                    {t('forgotPassword.resend')}
                                </Button>
                                <Button
                                    className="flex-1"
                                    onClick={onLogin}
                                >
                                    {t('forgotPassword.goToLogin')}
                                </Button>
                            </div>
                        </div>
                    ) : (
                        <Form {...form}>
                            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
                                <FormField
                                    control={form.control}
                                    name="email"
                                    render={({ field }) => (
                                        <FormItem>
                                            <FormLabel>{t('forgotPassword.emailLabel')}</FormLabel>
                                            <FormControl>
                                                <Input
                                                    type="email"
                                                    autoComplete="email"
                                                    placeholder={t('forgotPassword.emailPlaceholder')}
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
                                <Button
                                    type="submit"
                                    disabled={loading}
                                    className="w-full"
                                    size="lg"
                                >
                                    {loading ? (
                                        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                                    ) : null}
                                    {t('forgotPassword.submit')}
                                </Button>
                                <Button
                                    type="button"
                                    variant="ghost"
                                    className="w-full"
                                    onClick={onLogin}
                                >
                                    <ChevronLeft className="h-4 w-4" aria-hidden="true" />
                                    {t('forgotPassword.backToLogin')}
                                </Button>
                            </form>
                        </Form>
                    )}
                </CardContent>
            </Card>
        </div>
    );
};

export default ForgotPasswordPage;
