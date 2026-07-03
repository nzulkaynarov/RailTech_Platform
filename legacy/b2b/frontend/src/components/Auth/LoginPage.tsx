import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Train, Loader2, AlertCircle, Eye, EyeOff } from 'lucide-react';
import { useAuthStore } from '@/store/authStore';
import { LanguageSwitcher } from '@/components/ui/LanguageSwitcher';

import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card';
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
    onRegister?: () => void;
    onForgotPassword?: () => void;
}

export const LoginPage: React.FC<LoginPageProps> = ({ onNavigate, onRegister, onForgotPassword }) => {
    const { t } = useTranslation();
    const { login, isLoading } = useAuthStore();
    const [showPassword, setShowPassword] = useState(false);
    const [serverError, setServerError] = useState('');

    const form = useForm<LoginFormData>({
        resolver: zodResolver(createLoginSchema(t)),
        defaultValues: { email: '', password: '' },
    });

    const onSubmit = async (data: LoginFormData) => {
        setServerError('');
        try {
            await login(data.email, data.password);
            onNavigate?.('dashboard');
        } catch (err: unknown) {
            const raw = err instanceof Error ? err.message : '';
            let msg: string;
            if (raw === 'TOO_MANY_LOGIN_ATTEMPTS') {
                // SEC-06 per-account lockout — friendly, localized message.
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
                            {t('auth.loginTitle')}
                        </CardTitle>
                        <CardDescription>
                            {t('auth.loginSubtitle')}
                        </CardDescription>
                    </CardHeader>

                    <CardContent>
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
                    </CardContent>

                    <CardFooter className="flex-col border-t pt-6">
                        <p className="text-muted-foreground text-sm">{t('auth.newCompany')}</p>
                        <Button variant="link" className="mt-1" onClick={onRegister}>
                            {t('auth.registerLink')} →
                        </Button>
                    </CardFooter>
                </Card>
            </div>
        </div>
    );
};
