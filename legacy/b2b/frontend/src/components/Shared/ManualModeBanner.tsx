import { AlertTriangle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Alert, AlertDescription } from '@/components/ui/alert';

interface ManualModeBannerProps {
  kind: 'payment' | 'esign';
}

export function ManualModeBanner({ kind }: ManualModeBannerProps) {
  const { t } = useTranslation();
  return (
    <Alert variant="default" className="border-warning/40 bg-warning/5">
      <AlertTriangle className="h-4 w-4 text-warning" />
      <AlertDescription className="text-xs">
        {t(`manualMode.${kind}`)}
      </AlertDescription>
    </Alert>
  );
}
