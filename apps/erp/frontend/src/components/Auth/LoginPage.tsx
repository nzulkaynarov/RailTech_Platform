import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Train, Loader2, AlertCircle, Eye, EyeOff } from 'lucide-react';
import { useAuthStore } from '@/store/authStore';
import { LanguageSwitcher } from '@/components/ui/LanguageSwitcher';

import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Form, FormField, FormItem, FormLabel, FormControl, FormMessage } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';

const createLoginSchema = (t: (key: string) => string) =>
    z.object({
        email: z.string().min(1, t('auth.validation.emailRequired')).max(254),
        password: z.string().min(1, t('auth.validation.passwordRequired')).max(128),
    });

type LoginFormData = z.infer<ReturnType<typeof createLoginSchema>>;

interface LoginPageProps {
    onNavigate?: (target: string) => void;
    onForgotPassword?: () => void;
}

export const LoginPage: React.FC<LoginPageProps> = ({ onNavigate, onForgotPassword }) => {
    const { t } = useTranslation();
    const { login, isLoading } = useAuthStore();
    const [showPassword, setShowPassword] = useState(false);
    const [serverError, setServerError] = useState('');
    const [twoFactorRequired, setTwoFactorRequired] = useState(false);
    const [tempToken, setTempToken] = useState<string | null>(null);
    const [totpCode, setTotpCode] = useState('');

    const form = useForm<LoginFormData>({
        resolver: zodResolver(createLoginSchema(t)),
        defaultValues: { email: '', password: '' },
    });

    const onSubmit = async (data: LoginFormData) => {
        setServerError('');
        try {
            const res = await login(data.email, data.password);
            if (res && res.twoFactorRequired && res.tempToken) {
                setTwoFactorRequired(true);
                setTempToken(res.tempToken);
                return;
            }
            onNavigate?.('dashboard');
        } catch (err: unknown) {
            const raw = err instanceof Error ? err.message : '';
            let msg: string;
            if (raw === 'TOO_MANY_LOGIN_ATTEMPTS' || raw.toLowerCase().includes('throttled')) {
                // Both rate-limit responses (SEC-06 account lockout code + the
                // per-IP DRF throttle's English "Request was throttled" 429) →
                // one friendly, localized message.
                msg = t('auth.tooManyAttempts');
            } else if (raw.startsWith('auth.')) {
                // Store handed back an i18n key (no server detail) — localize it.
                msg = t(raw);
            } else {
                msg = raw || t('auth.genericError');
            }
            setServerError(msg);
        }
    };

    const on2FASubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setServerError('');
        if (!tempToken) return;
        if (!totpCode || totpCode.length !== 6) {
            setServerError(t('auth.validation.totpLength'));
            return;
        }
        try {
            const { login2FA } = useAuthStore.getState();
            await login2FA(tempToken, totpCode);
            onNavigate?.('dashboard');
        } catch (err: unknown) {
            const raw = err instanceof Error ? err.message : '';
            let msg: string;
            if (raw === '2FA_INVALID_CODE') {
                msg = t('auth.invalid2faCode');
            } else if (raw === '2FA_TICKET_INVALID') {
                // The 5-minute ticket expired (or 2FA state changed) — restart login.
                msg = t('auth.ticketExpired');
                setTwoFactorRequired(false);
                setTempToken(null);
                setTotpCode('');
            } else if (raw === 'TOO_MANY_LOGIN_ATTEMPTS' || raw.toLowerCase().includes('throttled')) {
                msg = t('auth.tooManyAttempts');
            } else if (raw.startsWith('auth.')) {
                msg = t(raw);
            } else {
                msg = raw || t('auth.genericError');
            }
            setServerError(msg);
        }
    };

    return (
        <div className="flex min-h-screen items-center justify-center bg-background p-8">
            {/* Language switcher */}
            <div className="absolute top-4 right-4 z-20">
                <LanguageSwitcher />
            </div>

            <div className="w-full max-w-md">
                {/* Logo */}
                <div className="flex items-center justify-center gap-3 mb-10">
                    <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary">
                        <Train className="h-6 w-6 text-primary-foreground" />
                    </div>
                    <span className="text-3xl font-black tracking-tight text-foreground">
                        Rail<span className="text-primary">Tech</span>{' '}
                        <span className="text-muted-foreground font-medium">B2B</span>
                    </span>
                </div>

                <Card>
                    <CardHeader>
                        <CardTitle className="text-2xl font-black">
                            {twoFactorRequired ? t('auth.login2faTitle') : t('auth.loginTitle')}
                        </CardTitle>
                        <CardDescription>
                            {twoFactorRequired ? t('auth.login2faSubtitle') : t('auth.loginSubtitle')}
                        </CardDescription>
                    </CardHeader>

                    <CardContent>
                        {twoFactorRequired ? (
                            <form onSubmit={on2FASubmit} className="space-y-6" noValidate>
                                <div className="space-y-2">
                                    <label className="text-sm font-medium leading-none">
                                        {t('auth.totpLabel')}
                                    </label>
                                    <Input
                                        type="text"
                                        inputMode="numeric"
                                        pattern="[0-9]*"
                                        maxLength={6}
                                        placeholder={t('auth.totpPlaceholder')}
                                        value={totpCode}
                                        onChange={(e) => setTotpCode(e.target.value.replace(/[^0-9]/g, ''))}
                                        className="text-center text-2xl tracking-widest font-mono"
                                        autoFocus
                                    />
                                </div>

                                {serverError && (
                                    <Alert variant="destructive">
                                        <AlertCircle className="size-4" />
                                        <AlertDescription>{serverError}</AlertDescription>
                                    </Alert>
                                )}

                                <Button
                                    type="submit"
                                    disabled={isLoading}
                                    className="w-full"
                                    size="lg"
                                >
                                    {isLoading && <Loader2 className="size-4 animate-spin" />}
                                    {t('auth.submit2faButton')}
                                </Button>
                                <div className="text-center">
                                    <Button
                                        type="button"
                                        variant="link"
                                        className="h-auto p-0 text-xs"
                                        onClick={() => {
                                            setTwoFactorRequired(false);
                                            setTempToken(null);
                                            setTotpCode('');
                                            setServerError('');
                                        }}
                                    >
                                        ← {t('auth.login')}
                                    </Button>
                                </div>
                            </form>
                        ) : (
                            <Form {...form}>
                                <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6" noValidate>
                                    {/* Email */}
                                    <FormField
                                        control={form.control}
                                        name="email"
                                        render={({ field }) => (
                                            <FormItem>
                                                <FormLabel>{t('auth.emailLabel')}</FormLabel>
                                                <FormControl>
                                                    <Input
                                                        type="email"
                                                        autoComplete="email"
                                                        placeholder={t('auth.emailPlaceholder')}
                                                        {...field}
                                                    />
                                                </FormControl>
                                                <FormMessage />
                                            </FormItem>
                                        )}
                                    />

                                    {/* Password */}
                                    <FormField
                                        control={form.control}
                                        name="password"
                                        render={({ field }) => (
                                            <FormItem>
                                                <FormLabel>{t('auth.passwordLabel')}</FormLabel>
                                                <FormControl>
                                                    <div className="relative">
                                                        <Input
                                                            type={showPassword ? 'text' : 'password'}
                                                            autoComplete="current-password"
                                                            placeholder={t('auth.passwordPlaceholder')}
                                                            className="pr-10"
                                                            {...field}
                                                        />
                                                        <Button
                                                            type="button"
                                                            variant="ghost"
                                                            size="icon"
                                                            className="absolute right-0 top-0 h-full px-3 hover:bg-transparent"
                                                            onClick={() => setShowPassword(p => !p)}
                                                            aria-label={showPassword ? t('auth.hidePassword') : t('auth.showPassword')}
                                                        >
                                                            {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                                                        </Button>
                                                    </div>
                                                </FormControl>
                                                <FormMessage />
                                            </FormItem>
                                        )}
                                    />

                                    {/* Server Error */}
                                    {serverError && (
                                        <Alert variant="destructive">
                                            <AlertCircle className="size-4" />
                                            <AlertDescription>{serverError}</AlertDescription>
                                        </Alert>
                                    )}

                                    {/* Submit */}
                                    <Button
                                        type="submit"
                                        disabled={isLoading}
                                        className="w-full"
                                        size="lg"
                                    >
                                        {isLoading && <Loader2 className="size-4 animate-spin" />}
                                        {t('auth.submitButton')}
                                    </Button>
                                    {onForgotPassword ? (
                                        <div className="text-center">
                                            <Button
                                                type="button"
                                                variant="link"
                                                className="h-auto p-0 text-xs"
                                                onClick={onForgotPassword}
                                            >
                                                {t('auth.forgotPassword')}
                                            </Button>
                                        </div>
                                    ) : null}
                                </form>
                            </Form>
                        )}
                    </CardContent>
                </Card>
            </div>
        </div>
    );
};
