import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Train, Loader2, AlertCircle, Eye, EyeOff, CheckCircle2 } from 'lucide-react';
import { useAuthStore } from '@/store/authStore';
import { LanguageSwitcher } from '@/components/ui/LanguageSwitcher';
import { cn } from '@/lib/utils';

import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card';
import { Form, FormField, FormItem, FormLabel, FormControl, FormMessage } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';

const loginSchema = z.object({
    email: z.string().min(1, 'auth.emailLabel').max(254),
    password: z.string().min(1, 'auth.passwordLabel').max(128),
});

type LoginFormData = z.infer<typeof loginSchema>;

const isDev = import.meta.env.DEV;

interface LoginPageProps {
    onNavigate?: (target: string) => void;
    onRegister?: () => void;
}

export const LoginPage: React.FC<LoginPageProps> = ({ onNavigate, onRegister }) => {
    const { t } = useTranslation();
    const { login, isLoading } = useAuthStore();
    const [showPassword, setShowPassword] = useState(false);
    const [serverError, setServerError] = useState('');

    const form = useForm<LoginFormData>({
        resolver: zodResolver(loginSchema),
        defaultValues: { email: '', password: '' },
    });

    const onSubmit = async (data: LoginFormData) => {
        setServerError('');
        try {
            await login(data.email, data.password);
            onNavigate?.('dashboard');
        } catch (err: unknown) {
            const msg = err instanceof Error ? err.message : t('auth.genericError');
            setServerError(msg);
        }
    };

    return (
        <div className="flex min-h-screen bg-background font-sans">
            {/* ─── Left Side: Product Presentation ─── */}
            <div className="hidden lg:flex w-1/2 relative bg-card dark:bg-card overflow-hidden flex-col justify-between p-16">
                <div className="absolute top-0 right-0 w-[500px] h-[500px] bg-primary/20 blur-[120px] rounded-full pointer-events-none transform translate-x-1/3 -translate-y-1/3" />
                <div className="absolute bottom-0 left-0 w-[400px] h-[400px] bg-primary/20 blur-[100px] rounded-full pointer-events-none transform -translate-x-1/3 translate-y-1/3" />

                <div className="relative z-10 flex items-center gap-3">
                    <div className="w-10 h-10 bg-primary rounded-xl flex items-center justify-center shadow-lg shadow-primary/30">
                        <Train className="w-5 h-5 text-white" aria-hidden="true" />
                    </div>
                    <span className="text-2xl font-black text-white tracking-tight">
                        Rail<span className="text-primary">Tech</span>{' '}
                        <span className="text-muted-foreground font-medium">B2B</span>
                    </span>
                </div>

                <div className="relative z-10 my-auto w-full max-w-xl">
                    <h1 className="text-4xl xl:text-5xl font-bold text-white mb-6 leading-tight">
                        {t('landing.heroTitle', {
                            interpolation: { escapeValue: false },
                        }).split(/<highlight>|<\/highlight>/).map((part, i) =>
                            i === 1 ? <span key={i} className="text-primary">{part}</span> : <React.Fragment key={i}>{part}</React.Fragment>
                        )}
                    </h1>
                    <p className="text-lg text-muted-foreground mb-12">
                        {t('landing.heroSubtitle')}
                    </p>

                    <div className="space-y-6">
                        <FeatureCard
                            icon={<CheckCircle2 className="w-5 h-5 text-primary" />}
                            iconBg="bg-primary/20"
                            title={t('landing.featureSmartMatch')}
                            description={t('landing.featureSmartMatchDesc')}
                        />
                        <FeatureCard
                            icon={<CheckCircle2 className="w-5 h-5 text-primary" />}
                            iconBg="bg-primary/20"
                            title={t('landing.featureUnitEconomics')}
                            description={t('landing.featureUnitEconomicsDesc')}
                        />
                    </div>
                </div>

                <div className="relative z-10 flex items-center justify-between text-sm text-muted-foreground">
                    <div>{t('common.copyright', { year: new Date().getFullYear() })}</div>
                    <a href="https://railtech.uz" className="hover:text-white transition-colors">
                        {t('common.corporateSite')} ↗
                    </a>
                </div>
            </div>

            {/* ─── Right Side: Auth Form ─── */}
            <div className="w-full lg:w-1/2 flex items-center justify-center p-8 relative">
                {/* Mobile Background */}
                <div className="absolute inset-0 bg-background flex lg:hidden" aria-hidden="true">
                    <div className="absolute top-0 right-0 w-96 h-96 bg-primary/15 blur-[120px] rounded-full" />
                    <div className="absolute bottom-0 left-0 w-72 h-72 bg-primary/10 blur-[80px] rounded-full" />
                </div>

                {/* Language switcher (top-right) */}
                <div className="absolute top-4 right-4 z-20">
                    <LanguageSwitcher />
                </div>

                <div className="relative z-10 w-full max-w-md">
                    {/* Mobile Logo */}
                    <div className="flex lg:hidden items-center justify-center gap-3 mb-10">
                        <div className="w-12 h-12 bg-primary rounded-2xl flex items-center justify-center shadow-2xl">
                            <Train className="w-6 h-6 text-white" aria-hidden="true" />
                        </div>
                        <span className="text-3xl font-black text-white tracking-tight">
                            Rail<span className="text-primary">Tech</span>
                        </span>
                    </div>

                    <Card className="border-border lg:border-none shadow-2xl lg:shadow-none bg-card lg:bg-transparent">
                        <CardHeader className="pb-0">
                            <CardTitle className="text-3xl font-black">
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
                                                <FormMessage>{form.formState.errors.email && t('errors.validationFailed')}</FormMessage>
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
                                                <FormMessage>{form.formState.errors.password && t('errors.validationFailed')}</FormMessage>
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

                    {/* Dev-only hint box — ONLY in development */}
                    {isDev && (
                        <div className="mt-8 p-4 rounded-xl bg-amber-50/80 border border-amber-200/50 text-center max-w-sm mx-auto">
                            <p className="text-xs font-semibold text-amber-600 mb-2 uppercase tracking-wide">Dev Only</p>
                            <div className="space-y-1 text-xs font-mono text-amber-700/80">
                                <p>client@test.uz / client123</p>
                                <p>manager@railtech.uz / manager123</p>
                                <p>admin@railtech.uz / admin123</p>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

/* ─── Feature card sub-component ─── */
interface FeatureCardProps {
    icon: React.ReactNode;
    iconBg: string;
    title: string;
    description: string;
}

const FeatureCard: React.FC<FeatureCardProps> = ({ icon, iconBg, title, description }) => (
    <div className="flex items-start gap-4 p-4 rounded-xl bg-white/5 border border-white/10">
        <div className={cn("mt-1 p-2 rounded-lg", iconBg)} aria-hidden="true">{icon}</div>
        <div>
            <h3 className="text-white font-bold mb-1">{title}</h3>
            <p className="text-sm text-white/60">{description}</p>
        </div>
    </div>
);
