import { AlertTriangle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { useUserStore } from '@/store/userStore';

interface ManualModeBannerProps {
  kind: 'payment' | 'esign';
}

/**
 * Reminds Platform Admin / seller-side staff that payment & e-sign are on the
 * manual pipeline (no Click/Payme/E-IMZO yet). Hidden for buyers — they don't
 * need to know about internal tech debt, only about the button to click.
 */
export function ManualModeBanner({ kind }: ManualModeBannerProps) {
  const { t } = useTranslation();
  const role = useUserStore((s) => s.role);
  const activeStatus = useUserStore((s) => s.activeStatus);
  const showForAudience =
    role === 'ADMIN' || activeStatus === 'SELLER';
  if (!showForAudience) return null;
  return (
    <Alert variant="default" className="border-warning/40 bg-warning/5">
      <AlertTriangle className="h-4 w-4 text-warning" />
      <AlertDescription className="text-xs">
        {t(`manualMode.${kind}`)}
      </AlertDescription>
    </Alert>
  );
}
