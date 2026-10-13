import React, { useState } from 'react';
import { useTranslation, Trans } from 'react-i18next';
import { UserPlus, Shield, CheckCircle, Loader2, AlertCircle } from 'lucide-react';
import { z } from 'zod';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { accountsApi } from '@/api/accountsApi';
import { cn } from '@/lib/utils';
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
import { PhoneInputUz } from '@/components/Shared/PhoneInputUz';

const createRegistrationSchema = (t: (key: string) => string) =>
	z.object({
		email: z.string().email(t('registration.validation.email')),
		first_name: z.string().min(2, t('registration.validation.minChars')),
		last_name: z.string().min(2, t('registration.validation.minChars')),
		phone: z.string().regex(/^\+998\d{9}$/, t('registration.validation.phone')),
	});

type RegistrationData = z.infer<ReturnType<typeof createRegistrationSchema>>;

export const KYCRegistrationForm: React.FC = () => {
	const { t } = useTranslation();
	const [step, setStep] = useState(1);
	const [error, setError] = useState('');

	const registrationSchema = createRegistrationSchema(t);

	const form = useForm<RegistrationData>({
		resolver: zodResolver(registrationSchema),
		defaultValues: {
			email: '',
			first_name: '',
			last_name: '',
			phone: '+998',
		},
	});

	const { isSubmitting } = form.formState;

	const onSubmit = async (data: RegistrationData) => {
		setError('');
		try {
			await accountsApi.registerInterest(data);
			// Anti-enumeration (P2): the backend ALWAYS returns 201 with the same neutral
			// body — a free email, an existing active account, and a pending one are
			// indistinguishable. There is no "email already exists" branch to surface;
			// we always land on the neutral "check your inbox" success screen. A caught
			// error here means a genuine transport/rate-limit failure, never account state.
			setStep(2);
		} catch {
			setError(t('registration.genericError'));
		}
	};

	return (
		<div className="min-h-screen bg-background flex items-center justify-center p-6 font-sans">
			<Card className="w-full max-w-xl">
				<CardHeader className="p-8 pb-4">
					<div className="flex items-center gap-3 mb-6">
						<div className="w-10 h-10 rounded-xl bg-primary flex items-center justify-center">
							<UserPlus className="w-5 h-5 text-primary-foreground" />
						</div>
						<div>
							<CardTitle className="text-2xl font-black tracking-tight">
								{t('registration.title')}
							</CardTitle>
							<CardDescription className="text-sm font-medium">
								{t('registration.subtitle')}
							</CardDescription>
						</div>
					</div>

					<div
						className="flex gap-2 h-1.5 w-full bg-muted rounded-full overflow-hidden"
						role="progressbar"
						aria-valuenow={step}
						aria-valuemin={1}
						aria-valuemax={2}
						aria-label={t('registration.progress')}
					>
						<div
							className={cn(
								'h-full bg-primary transition-all duration-500',
								step === 1 ? 'w-1/2' : 'w-full'
							)}
						/>
					</div>
				</CardHeader>

				<CardContent className="p-8 pt-6">
					{step === 1 && (
						<Form {...form}>
							<form
								onSubmit={form.handleSubmit(onSubmit)}
								className="space-y-6"
							>
								<div className="space-y-4">
									<label className="text-xs font-bold text-muted-foreground uppercase tracking-widest flex items-center gap-2">
										<Shield className="w-3 h-3" /> {t('registration.stepContact')}
									</label>

									<div className="grid grid-cols-2 gap-4">
										<FormField
											control={form.control}
											name="first_name"
											render={({ field }) => (
												<FormItem>
													<FormLabel>{t('registration.firstName')}</FormLabel>
													<FormControl>
														<Input
															placeholder={t('registration.firstNamePlaceholder')}
															{...field}
														/>
													</FormControl>
													<FormMessage />
												</FormItem>
											)}
										/>

										<FormField
											control={form.control}
											name="last_name"
											render={({ field }) => (
												<FormItem>
													<FormLabel>{t('registration.lastName')}</FormLabel>
													<FormControl>
														<Input
															placeholder={t('registration.lastNamePlaceholder')}
															{...field}
														/>
													</FormControl>
													<FormMessage />
												</FormItem>
											)}
										/>

										<FormField
											control={form.control}
											name="phone"
											render={({ field }) => (
												<FormItem className="col-span-2">
													<FormLabel>{t('registration.phoneLabel')}</FormLabel>
													<FormControl>
														<PhoneInputUz
															value={field.value}
															onChange={field.onChange}
															onBlur={field.onBlur}
															name={field.name}
															placeholder={t('registration.phonePlaceholder')}
														/>
													</FormControl>
													<FormMessage />
												</FormItem>
											)}
										/>
									</div>

									<FormField
										control={form.control}
										name="email"
										render={({ field }) => (
											<FormItem>
												<FormLabel>
													{t('registration.emailLabel')}
												</FormLabel>
												<FormControl>
													<Input
														type="email"
														placeholder={t('registration.emailPlaceholder')}
														{...field}
													/>
												</FormControl>
												<FormMessage />
											</FormItem>
										)}
									/>
								</div>

								{error && (
									<Alert variant="destructive">
										<AlertCircle className="h-4 w-4" />
										<AlertDescription>{error}</AlertDescription>
									</Alert>
								)}

								<Button
									type="submit"
									disabled={isSubmitting}
									className="w-full"
									size="lg"
								>
									{isSubmitting && (
										<Loader2 className="w-4 h-4 animate-spin" />
									)}
									{t('registration.submit')}
								</Button>
							</form>
						</Form>
					)}

					{step === 2 && (
						<div className="text-center py-8">
							<div className="w-24 h-24 bg-chart-2/20 rounded-full flex items-center justify-center mx-auto mb-6 border border-chart-2/30">
								<CheckCircle className="w-12 h-12 text-chart-2" />
							</div>
							<h3 className="text-2xl font-black text-foreground mb-2">
								{t('registration.emailSent')}
							</h3>
							<p className="text-muted-foreground mb-8 max-w-xs mx-auto text-sm leading-relaxed">
								<Trans
									i18nKey="registration.emailSentHint"
									values={{ email: form.getValues('email') }}
									components={{ strong: <strong /> }}
								/>
							</p>
							<div className="space-y-4">
								<p className="text-xs text-muted-foreground font-medium">
									{t('registration.waitHint')}
								</p>
								<div className="flex justify-center">
									<Button
										variant="link"
										onClick={() => {
											window.history.pushState(null, '', '/');
											window.dispatchEvent(new PopStateEvent('popstate'));
										}}
									>
										{t('registration.backToLogin')}
									</Button>
								</div>
							</div>
						</div>
					)}
				</CardContent>
			</Card>
		</div>
	);
};
