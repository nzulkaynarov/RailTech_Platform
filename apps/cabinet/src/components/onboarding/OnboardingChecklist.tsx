import { useState, useCallback, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Building2,
  CheckCircle2,
  Circle,
  FileSignature,
  Inbox,
  PackageOpen,
  Send,
  Sparkles,
  Users,
  X,
  ChevronRight,
  type LucideIcon,
} from 'lucide-react';

import {
  useCompany,
  useCompanyPartnerApplication,
  usePartnerProducts,
  useRequests,
  useTeam,
  useTelegramStatus,
} from '@/api/queries';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { useTelegramStep } from '@/onboarding/telegramStep';
import { dismissChecklist, isChecklistDismissed } from '@/onboarding/checklistState';
import { isMiniApp } from '@/telegram/webapp';
import { cn } from '@/lib/utils';
import { useHasModule, useMe } from '@/session/useMe';

export interface OnboardingStepItem {
  id: string;
  titleKey: string;
  descKey: string;
  icon: LucideIcon;
  done: boolean;
  to?: string;
  onClick?: () => void;
}

/**
 * Чек-лист «Первые шаги в кабинете» (волна J1, ADR-0022/0023, карта пути контрагента):
 * - Вычисляется из реальных данных портала (реквизиты, Telegram, первый запрос / прайс, коллеги).
 * - Адаптируется под роли (`client`, `partner`, кандидат в партнёры).
 * - Шаг Telegram вызывает нативную привязку через `useTelegramStep`.
 * - Можно скрыть в текущем браузере (`localStorage`).
 */
export function OnboardingChecklist() {
  const { t } = useTranslation();
  const me = useMe().data;
  const isClient = me?.roles?.includes('client') ?? true;
  const isPartner = me?.roles?.includes('partner') ?? false;
  const hasRequests = useHasModule('catalog_requests');
  const hasMyProducts = useHasModule('my_products');

  const [dismissed, setDismissed] = useState(isChecklistDismissed);

  const inMiniApp = isMiniApp();
  const companyQuery = useCompany({ enabled: !dismissed });
  const telegramStatus = useTelegramStatus({ enabled: !dismissed && !inMiniApp });
  const telegramStep = useTelegramStep({ enabled: !dismissed && !inMiniApp });
  const teamQuery = useTeam({ enabled: !dismissed });
  const requestsQuery = useRequests({ enabled: !dismissed && hasRequests });
  const partnerProductsQuery = usePartnerProducts(
    { page: 1, page_size: 1 },
    { enabled: !dismissed && hasMyProducts },
  );
  const partnerAppQuery = useCompanyPartnerApplication({ enabled: !dismissed && !isPartner });

  const handleDismiss = useCallback(() => {
    dismissChecklist();
    setDismissed(true);
  }, []);

  const steps = useMemo<OnboardingStepItem[]>(() => {
    const list: OnboardingStepItem[] = [];

    // 1. Реквизиты компании
    const company = companyQuery.data;
    const hasRequisites = Boolean(
      (company?.inn || company?.registration_number) && company?.legal_address,
    );
    list.push({
      id: 'company',
      titleKey: 'onboarding.companyRequisites',
      descKey: 'onboarding.companyRequisitesDesc',
      icon: Building2,
      done: hasRequisites,
      to: '/company',
    });

    // 2. Уведомления Telegram
    const isTelegramLinked = inMiniApp || Boolean(telegramStatus.data?.linked);
    list.push({
      id: 'telegram',
      titleKey: 'onboarding.telegramNotif',
      descKey: 'onboarding.telegramNotifDesc',
      icon: Send,
      done: isTelegramLinked,
      onClick: telegramStep.connect,
    });

    // 3. Ролевое действие
    if (isPartner || hasMyProducts) {
      const hasProducts = Boolean(
        partnerProductsQuery.data && partnerProductsQuery.data.total > 0,
      );
      list.push({
        id: 'price-list',
        titleKey: 'onboarding.uploadPriceList',
        descKey: 'onboarding.uploadPriceListDesc',
        icon: PackageOpen,
        done: hasProducts,
        to: '/my-products',
      });
    } else if (partnerAppQuery.data?.has_application) {
      const isAgreedOrApproved =
        partnerAppQuery.data.application?.status === 'candidate_agreed' ||
        partnerAppQuery.data.application?.status === 'approved';
      list.push({
        id: 'partner-contract',
        titleKey: 'onboarding.partnerContract',
        descKey: 'onboarding.partnerContractDesc',
        icon: FileSignature,
        done: isAgreedOrApproved,
        to: '/company',
      });
    } else if (isClient || hasRequests) {
      const hasFirstRequest = Boolean(
        requestsQuery.data && requestsQuery.data.length > 0,
      );
      list.push({
        id: 'first-request',
        titleKey: 'onboarding.firstRequest',
        descKey: 'onboarding.firstRequestDesc',
        icon: Inbox,
        done: hasFirstRequest,
        to: '/requests/new',
      });
    }

    // 4. Команда компании
    const hasTeam = Boolean(teamQuery.data && teamQuery.data.length > 1);
    list.push({
      id: 'team',
      titleKey: 'onboarding.inviteTeam',
      descKey: 'onboarding.inviteTeamDesc',
      icon: Users,
      done: hasTeam,
      to: '/team',
    });

    return list;
  }, [
    inMiniApp,
    companyQuery.data,
    telegramStatus.data?.linked,
    telegramStep.connect,
    isPartner,
    hasMyProducts,
    partnerProductsQuery.data,
    partnerAppQuery.data,
    isClient,
    hasRequests,
    requestsQuery.data,
    teamQuery.data,
  ]);

  if (dismissed) return null;

  const completedCount = steps.filter((s) => s.done).length;
  const totalCount = steps.length;
  const allCompleted = completedCount === totalCount;

  return (
    <Card className="portal-card group relative mb-6 border-border/80 bg-card/80 backdrop-blur-xs transition-colors hover:border-border">
      <CardContent className="p-4 sm:p-5">
        <div className="flex items-center justify-between gap-3 pb-3">
          <div className="flex items-center gap-2.5">
            <div className="flex size-7 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Sparkles className="size-4" aria-hidden="true" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-foreground">
                {t('onboarding.title')}
              </h2>
              <p className="text-xs text-muted-foreground">
                {allCompleted
                  ? t('onboarding.allDone')
                  : t('onboarding.progress', { done: completedCount, total: totalCount })}
              </p>
            </div>
          </div>

          <Button
            variant="ghost"
            size="icon"
            className="size-7 rounded-lg text-muted-foreground hover:bg-accent hover:text-foreground"
            onClick={handleDismiss}
            aria-label={t('onboarding.dismiss')}
            title={t('onboarding.dismiss')}
          >
            <X className="size-4" aria-hidden="true" />
          </Button>
        </div>

        {/* Индикатор прогресса */}
        <div className="mb-4 h-1.5 w-full overflow-hidden rounded-full bg-muted">
          <div
            className={cn(
              'h-full transition-all duration-500 ease-out',
              allCompleted ? 'bg-success' : 'bg-primary',
            )}
            style={{ width: `${(completedCount / Math.max(totalCount, 1)) * 100}%` }}
          />
        </div>

        {/* Список шагов */}
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {steps.map((step) => {
            const content = (
              <div
                className={cn(
                  'flex items-center justify-between gap-3 rounded-xl border p-3 transition-colors',
                  step.done
                    ? 'border-border/40 bg-muted/30 text-muted-foreground'
                    : 'border-border bg-background hover:border-ring/50 hover:bg-accent/40 text-foreground',
                )}
              >
                <div className="flex min-w-0 items-center gap-2.5">
                  {step.done ? (
                    <CheckCircle2
                      className="size-4 shrink-0 text-success"
                      aria-hidden="true"
                    />
                  ) : (
                    <Circle
                      className="size-4 shrink-0 text-muted-foreground"
                      aria-hidden="true"
                    />
                  )}
                  <div className="min-w-0">
                    <p
                      className={cn(
                        'truncate text-xs font-medium',
                        step.done && 'line-through opacity-80',
                      )}
                    >
                      {t(step.titleKey)}
                    </p>
                    <p className="truncate text-xs text-muted-foreground">
                      {t(step.descKey)}
                    </p>
                  </div>
                </div>
                <ChevronRight
                  className="size-3.5 shrink-0 text-muted-foreground"
                  aria-hidden="true"
                />
              </div>
            );

            if (step.onClick) {
              return (
                <button
                  key={step.id}
                  type="button"
                  onClick={step.onClick}
                  className="w-full text-left outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-xl"
                >
                  {content}
                </button>
              );
            }

            return (
              <Link
                key={step.id}
                to={step.to ?? '#'}
                className="w-full outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-xl"
              >
                {content}
              </Link>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
