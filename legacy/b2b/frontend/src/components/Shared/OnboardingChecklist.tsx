import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
  CheckCircle2,
  Circle,
  ChevronRight,
  ShieldCheck,
  Users as UsersIcon,
  CreditCard,
  Rocket,
  FilePlus,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { useAuthStore } from '@/store/authStore';
import { useUserStore } from '@/store/userStore';
import { useMySubscription } from '@/hooks/useAccounts';
import { useDeals } from '@/hooks/useCRM';
import { cn } from '@/lib/utils';

interface OnboardingChecklistProps {
  onNavigate?: (target: string) => void;
}

interface Step {
  id: string;
  label: string;
  hint: string;
  icon: React.ComponentType<{ className?: string }>;
  done: boolean;
  action?: { label: string; target: string };
  appliesTo: 'all' | 'seller' | 'buyer';
}

const STORAGE_KEY = 'onboarding.dismissed';

function isDismissed(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === '1';
  } catch {
    return false;
  }
}

function markDismissed() {
  try {
    localStorage.setItem(STORAGE_KEY, '1');
  } catch {
    /* ignore */
  }
}

export function OnboardingChecklist({ onNavigate }: OnboardingChecklistProps) {
  const { t } = useTranslation();
  const user = useAuthStore((s) => s.user);
  const activeStatus = useUserStore((s) => s.activeStatus);
  const { data: sub } = useMySubscription();
  const { data: deals = [] } = useDeals();

  const isSeller = activeStatus === 'SELLER' || activeStatus === 'MANUFACTURER';
  const isBuyer = activeStatus === 'BUYER';

  const kycStatusCode =
    user?.primary_company?.verification_status_code
    ?? user?.company?.verification_status_code
    ?? null;
  const kycDone = kycStatusCode === 'L2_VERIFIED' || kycStatusCode === 'L3_CONTRACTED';
  const kycSubmitted = kycStatusCode === 'PROFILE_SUBMITTED';

  const profileDone = Boolean(user?.first_name && user?.last_name);
  const hasSubscription = Boolean(sub && (sub.status === 'ACTIVE' || sub.status === 'TRIAL'));
  const hasDeal = deals.length > 0;

  const steps: Step[] = useMemo(() => {
    const all: Step[] = [
      {
        id: 'profile',
        label: t('onboarding.steps.profile.label'),
        hint: t('onboarding.steps.profile.hint'),
        icon: UsersIcon,
        done: profileDone,
        action: !profileDone ? { label: t('onboarding.steps.profile.cta'), target: 'profile' } : undefined,
        appliesTo: 'all',
      },
      {
        id: 'kyc',
        label: t('onboarding.steps.kyc.label'),
        hint: kycSubmitted
          ? t('onboarding.steps.kyc.hintSubmitted')
          : t('onboarding.steps.kyc.hint'),
        icon: ShieldCheck,
        done: kycDone,
        action: !kycDone && !kycSubmitted ? { label: t('onboarding.steps.kyc.cta'), target: 'profile' } : undefined,
        appliesTo: 'all',
      },
      {
        id: 'subscription',
        label: t('onboarding.steps.subscription.label'),
        hint: t('onboarding.steps.subscription.hint'),
        icon: CreditCard,
        done: hasSubscription,
        action: !hasSubscription ? { label: t('onboarding.steps.subscription.cta'), target: 'my-subscription' } : undefined,
        appliesTo: 'seller',
      },
      {
        id: 'first-rfq',
        label: t('onboarding.steps.firstRfq.label'),
        hint: t('onboarding.steps.firstRfq.hint'),
        icon: FilePlus,
        done: hasDeal,
        action: !hasDeal ? { label: t('onboarding.steps.firstRfq.cta'), target: 'my-requests' } : undefined,
        appliesTo: 'buyer',
      },
    ];
    return all.filter((s) => s.appliesTo === 'all' || (s.appliesTo === 'seller' && isSeller) || (s.appliesTo === 'buyer' && isBuyer));
  }, [profileDone, kycDone, kycSubmitted, hasSubscription, hasDeal, isSeller, isBuyer, t]);

  const doneCount = steps.filter((s) => s.done).length;
  const total = steps.length;
  const percent = total === 0 ? 0 : Math.round((doneCount / total) * 100);
  const allDone = doneCount === total && total > 0;

  // Hide permanently once fully complete AND user dismissed.
  if (allDone && isDismissed()) return null;

  return (
    <Card className="border-primary/30 bg-primary/5">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Rocket className="h-4 w-4 text-primary" aria-hidden="true" />
            {t('onboarding.title')}
          </CardTitle>
          {allDone ? (
            <Button
              size="sm"
              variant="ghost"
              className="h-7 text-xs"
              onClick={() => {
                markDismissed();
                // force re-render via location hash toggle no-op — keep minimal
                window.dispatchEvent(new Event('onboarding:dismissed'));
              }}
            >
              {t('onboarding.hide')}
            </Button>
          ) : null}
        </div>
        <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
          <span>{t('onboarding.progress', { done: doneCount, total })}</span>
          <Progress value={percent} className="h-1.5 flex-1" />
          <span className="tabular-nums">{percent}%</span>
        </div>
      </CardHeader>
      <CardContent className="space-y-1 text-xs">
        {steps.map((step) => {
          const Icon = step.icon;
          return (
            <div
              key={step.id}
              className={cn(
                'flex items-center gap-2 rounded-md px-2 py-1.5',
                step.done && 'text-muted-foreground',
              )}
            >
              {step.done ? (
                <CheckCircle2 className="h-4 w-4 text-success" aria-hidden="true" />
              ) : (
                <Circle className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
              )}
              <Icon className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
              <div className="flex-1 min-w-0">
                <div className={cn('font-medium', step.done && 'line-through')}>
                  {step.label}
                </div>
                <div className="text-muted-foreground">{step.hint}</div>
              </div>
              {step.action ? (
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 text-xs"
                  onClick={() => onNavigate?.(step.action!.target)}
                  disabled={!onNavigate}
                >
                  {step.action.label}
                  <ChevronRight className="h-3 w-3" aria-hidden="true" />
                </Button>
              ) : null}
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
