import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Layers, ShoppingCart, Factory, Store, ArrowRight, ArrowLeft,
  Check, Mail, Building2, AlertTriangle, Info,
} from 'lucide-react';

import { cn } from '@/lib/utils';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { Alert, AlertDescription } from '@/components/ui/alert';

import {
  useUserStore,
  type CompanyStatus,
} from '@/store/userStore';

/* ─── Status Card ────────────────────────────────────────────────────── */

interface StatusOptionProps {
  status: CompanyStatus;
  selected: boolean;
  onSelect: () => void;
}

function StatusOption({ status, selected, onSelect }: StatusOptionProps) {
  const { t } = useTranslation();

  const icons: Record<CompanyStatus, React.ReactNode> = {
    BUYER: <ShoppingCart className="h-6 w-6" />,
    MANUFACTURER: <Factory className="h-6 w-6" />,
    SELLER: <Store className="h-6 w-6" />,
  };

  // No per-status raw colors — use semantic tokens for selected/unselected

  const capabilities = t(`onboarding.capabilities.${status}`, { returnObjects: true }) as string[];

  const displayCapabilities = Array.isArray(capabilities) ? capabilities.slice(0, 4) : [];

  return (
    <button
      className={cn(
        'relative flex h-full flex-col items-center rounded-xl border-2 p-5 text-center transition-all hover:shadow-md',
        selected ? 'border-primary bg-primary/5 text-primary' : 'border-border bg-card text-foreground hover:border-muted-foreground/30'
      )}
      onClick={onSelect}
    >
      {selected && (
        <div className="absolute right-3 top-3 flex h-6 w-6 items-center justify-center rounded-full bg-primary text-primary-foreground">
          <Check className="h-4 w-4" />
        </div>
      )}
      <div className={cn(
        'flex h-12 w-12 items-center justify-center rounded-xl',
        selected ? 'bg-primary/10' : 'bg-muted'
      )}>
        {icons[status]}
      </div>
      <h3 className="mt-3 text-base font-bold">{t(`companyStatus.${status}`)}</h3>
      <p className={cn('mt-1 text-sm leading-snug', selected ? 'opacity-80' : 'text-muted-foreground')}>
        {t(`companyStatusDesc.${status}`)}
      </p>
      <Separator className="my-3 w-full" />
      <ul className="space-y-1.5 w-full text-left">
        {displayCapabilities.map((cap) => (
          <li key={cap} className={cn('flex items-start gap-2 text-xs', selected ? 'opacity-80' : 'text-muted-foreground')}>
            <Check className="h-3 w-3 mt-0.5 shrink-0" />
            <span>{cap}</span>
          </li>
        ))}
      </ul>
    </button>
  );
}

/* ─── Main Onboarding Page ───────────────────────────────────────────── */

export function OnboardingPage() {
  const { t } = useTranslation();
  const { completeOnboarding } = useUserStore();
  const [step, setStep] = useState(1);

  // Form state
  const [email, setEmail] = useState('');
  const [companyName, setCompanyName] = useState('');
  const [companyInn, setCompanyInn] = useState('');
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [selectedStatus, setSelectedStatus] = useState<CompanyStatus | null>(null);

  const canProceedStep1 = email.includes('@') && companyName.length > 1;
  const canProceedStep2 = selectedStatus !== null;
  const canProceedStep3 = firstName.length > 0 && lastName.length > 0;

  const handleComplete = () => {
    if (!selectedStatus || !canProceedStep3) return;
    completeOnboarding({
      email,
      companyName,
      companyInn,
      selectedStatus,
      firstName,
      lastName,
    });
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 p-4">
      <div className={cn('w-full', step === 2 ? 'max-w-4xl' : 'max-w-2xl')}>
        {/* Logo */}
        <div className="flex items-center justify-center gap-2 mb-8">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <Layers className="h-5 w-5" />
          </div>
          <span className="text-2xl font-bold tracking-tight">RAILTECH</span>
        </div>

        {/* Step indicators */}
        <div className="flex items-center justify-center gap-2 mb-6">
          {[1, 2, 3].map((s) => (
            <div key={s} className="flex items-center gap-2">
              <div className={cn(
                'flex h-8 w-8 items-center justify-center rounded-full text-sm font-medium',
                s < step ? 'bg-primary text-primary-foreground' :
                  s === step ? 'bg-primary text-primary-foreground ring-2 ring-primary/30' :
                    'bg-muted text-muted-foreground'
              )}>
                {s < step ? <Check className="h-4 w-4" /> : s}
              </div>
              {s < 3 && <div className={cn('h-0.5 w-12', s < step ? 'bg-primary' : 'bg-muted')} />}
            </div>
          ))}
        </div>

        {/* Step 1: Email + Company */}
        {step === 1 && (
          <Card>
            <CardHeader className="text-center">
              <CardTitle className="text-xl">{t('onboarding.companyRegistration')}</CardTitle>
              <CardDescription>{t('onboarding.companyRegistrationDesc')}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="email">{t('onboarding.email')}</Label>
                <div className="relative">
                  <Mail className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    id="email"
                    type="email"
                    className="pl-9"
                    placeholder="company@example.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                  />
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="companyName">{t('onboarding.companyName')}</Label>
                <div className="relative">
                  <Building2 className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    id="companyName"
                    className="pl-9"
                    placeholder={t('onboarding.companyNamePlaceholder')}
                    value={companyName}
                    onChange={(e) => setCompanyName(e.target.value)}
                  />
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="inn">{t('onboarding.inn')}</Label>
                <Input
                  id="inn"
                  placeholder={t('onboarding.innPlaceholder')}
                  value={companyInn}
                  onChange={(e) => setCompanyInn(e.target.value)}
                />
              </div>
              <div className="flex justify-end pt-2">
                <Button className="gap-2" disabled={!canProceedStep1} onClick={() => setStep(2)}>
                  {t('onboarding.next')} <ArrowRight className="h-4 w-4" />
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Step 2: Status selection */}
        {step === 2 && (
          <Card>
            <CardHeader className="text-center">
              <CardTitle className="text-xl">{t('onboarding.selectCompanyStatus')}</CardTitle>
              <CardDescription>{t('onboarding.selectCompanyStatusDesc')}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-4 md:grid-cols-3">
                {(['BUYER', 'SELLER', 'MANUFACTURER'] as CompanyStatus[]).map((s) => (
                  <StatusOption
                    key={s}
                    status={s}
                    selected={selectedStatus === s}
                    onSelect={() => setSelectedStatus(s)}
                  />
                ))}
              </div>

              <Alert>
                <Info className="h-4 w-4" />
                <AlertDescription>
                  <p className="font-medium">{t('onboarding.statusUnderReview')}</p>
                  <p className="mt-0.5 text-muted-foreground">{t('onboarding.statusUnderReviewDesc')}</p>
                </AlertDescription>
              </Alert>

              <div className="flex justify-between pt-2">
                <Button variant="outline" className="gap-2" onClick={() => setStep(1)}>
                  <ArrowLeft className="h-4 w-4" /> {t('onboarding.back')}
                </Button>
                <Button className="gap-2" disabled={!canProceedStep2} onClick={() => setStep(3)}>
                  {t('onboarding.next')} <ArrowRight className="h-4 w-4" />
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Step 3: Personal info + Confirm */}
        {step === 3 && (
          <Card>
            <CardHeader className="text-center">
              <CardTitle className="text-xl">{t('onboarding.contactPerson')}</CardTitle>
              <CardDescription>{t('onboarding.contactPersonDesc')}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="firstName">{t('onboarding.firstName')}</Label>
                  <Input
                    id="firstName"
                    placeholder={t('onboarding.firstName')}
                    value={firstName}
                    onChange={(e) => setFirstName(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="lastName">{t('onboarding.lastName')}</Label>
                  <Input
                    id="lastName"
                    placeholder={t('onboarding.lastName')}
                    value={lastName}
                    onChange={(e) => setLastName(e.target.value)}
                  />
                </div>
              </div>

              {/* Summary */}
              <Card>
                <CardContent className="p-4 space-y-2">
                  <p className="text-sm font-medium">{t('onboarding.registrationSummary')}</p>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
                    <span className="text-muted-foreground">{t('onboarding.email')}:</span>
                    <span className="font-medium">{email}</span>
                    <span className="text-muted-foreground">{t('onboarding.company')}:</span>
                    <span className="font-medium">{companyName}</span>
                    {companyInn && (
                      <>
                        <span className="text-muted-foreground">{t('onboarding.inn')}:</span>
                        <span className="font-medium">{companyInn}</span>
                      </>
                    )}
                    <span className="text-muted-foreground">{t('onboarding.status')}:</span>
                    <Badge variant="outline" className="w-fit">
                      {selectedStatus ? t(`companyStatus.${selectedStatus}`) : '—'}
                    </Badge>
                    <span className="text-muted-foreground">{t('onboarding.role')}:</span>
                    <span className="font-medium">{t('onboarding.roleAdmin')}</span>
                  </div>
                </CardContent>
              </Card>

              <Alert>
                <AlertTriangle className="h-4 w-4" />
                <AlertDescription>{t('onboarding.registrationNote')}</AlertDescription>
              </Alert>

              <div className="flex justify-between pt-2">
                <Button variant="outline" className="gap-2" onClick={() => setStep(2)}>
                  <ArrowLeft className="h-4 w-4" /> {t('onboarding.back')}
                </Button>
                <Button className="gap-2" disabled={!canProceedStep3} onClick={handleComplete}>
                  <Check className="h-4 w-4" /> {t('onboarding.register')}
                </Button>
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
