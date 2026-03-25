import { useTranslation } from 'react-i18next';
import {
  Clock, CheckCircle2, XCircle, Layers, ShoppingCart, Factory, Store,
  RotateCcw, ArrowRight, Info,
} from 'lucide-react';

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { Alert, AlertDescription } from '@/components/ui/alert';

import {
  useUserStore,
  type CompanyStatus,
  type VerificationStatus,
} from '@/store/userStore';
import { useDemoStore } from '@/store/demoStore';

function StatusIcon({ status }: { status: CompanyStatus }) {
  switch (status) {
    case 'BUYER': return <ShoppingCart className="h-5 w-5" />;
    case 'MANUFACTURER': return <Factory className="h-5 w-5" />;
    case 'SELLER': return <Store className="h-5 w-5" />;
  }
}

function VerificationBadge({ v }: { v: VerificationStatus }) {
  const { t } = useTranslation();
  switch (v) {
    case 'pending':
      return (
        <Badge variant="secondary" className="gap-1 text-amber-700 border-amber-200 bg-amber-50">
          <Clock className="h-3 w-3" /> {t('verification.pending')}
        </Badge>
      );
    case 'verified':
      return (
        <Badge variant="secondary" className="gap-1 text-emerald-700 border-emerald-200 bg-emerald-50">
          <CheckCircle2 className="h-3 w-3" /> {t('verification.verified')}
        </Badge>
      );
    case 'rejected':
      return (
        <Badge variant="destructive" className="gap-1">
          <XCircle className="h-3 w-3" /> {t('verification.rejected')}
        </Badge>
      );
  }
}

export function PendingVerificationPage() {
  const { t } = useTranslation();
  const { company, profile, adminApproveStatus, enterMainApp, resetToOnboarding } = useUserStore();
  const { isDemoMode } = useDemoStore();

  const hasVerified = company.statusEntries.some((e) => e.verification === 'verified');

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 p-4">
      <div className="w-full max-w-lg">
        {/* Logo */}
        <div className="flex items-center justify-center gap-2 mb-8">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <Layers className="h-5 w-5" />
          </div>
          <span className="text-2xl font-bold tracking-tight">RAILTECH</span>
        </div>

        <Card>
          <CardHeader className="text-center">
            <div className="mx-auto mb-2 flex h-14 w-14 items-center justify-center rounded-full bg-muted">
              <Clock className="h-7 w-7 text-muted-foreground" />
            </div>
            <CardTitle className="text-xl">{t('verification.applicationUnderReview')}</CardTitle>
            <CardDescription>
              {t('verification.applicationUnderReviewDesc', { email: profile.email })}
            </CardDescription>
          </CardHeader>

          <CardContent className="space-y-4">
            {/* Company info */}
            <Card>
              <CardContent className="p-4 space-y-2">
                <p className="text-sm font-medium">{company.name}</p>
                {company.inn && <p className="text-xs text-muted-foreground">ИНН: {company.inn}</p>}
              </CardContent>
            </Card>

            {/* Status entries */}
            <div className="space-y-2">
              <p className="text-sm font-medium">{t('verification.requestedStatuses')}</p>
              {company.statusEntries.map((entry) => (
                <div key={entry.status} className="flex items-center justify-between rounded-lg border p-3">
                  <div className="flex items-center gap-3">
                    <StatusIcon status={entry.status} />
                    <span className="text-sm font-medium">{t(`companyStatus.${entry.status}`)}</span>
                  </div>
                  <VerificationBadge v={entry.verification} />
                </div>
              ))}
            </div>

            {/* Seller → manufacturer confirmation note */}
            {company.statusEntries.some((e) => e.status === 'SELLER' && e.verification === 'verified') && (
              <Alert>
                <Info className="h-4 w-4" />
                <AlertDescription>
                  <p className="text-xs">{t('verification.sellerPartnershipNote')}</p>
                </AlertDescription>
              </Alert>
            )}

            <Separator />

            {/* Simulation buttons — only visible in demo mode */}
            {isDemoMode && (
              <div className="space-y-2">
                <p className="text-xs text-muted-foreground font-medium">{t('verification.demoSimulation')}</p>
                <div className="flex flex-wrap gap-2">
                  {company.statusEntries
                    .filter((e) => e.verification === 'pending')
                    .map((entry) => (
                      <Button
                        key={entry.status}
                        variant="outline"
                        size="sm"
                        className="gap-1.5"
                        onClick={() => adminApproveStatus(entry.status)}
                      >
                        <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />
                        {t('verification.approve', { status: t(`companyStatus.${entry.status}`) })}
                      </Button>
                    ))}
                </div>
              </div>
            )}

            {/* Actions */}
            <div className="flex justify-between pt-2">
              <Button variant="ghost" size="sm" className="gap-2 text-muted-foreground" onClick={resetToOnboarding}>
                <RotateCcw className="h-3.5 w-3.5" /> {t('verification.startOver')}
              </Button>
              {hasVerified && (
                <Button className="gap-2" onClick={enterMainApp}>
                  {t('verification.enterSystem')} <ArrowRight className="h-4 w-4" />
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
