import { useTranslation } from 'react-i18next';
import { Download, FileSpreadsheet, PackageOpen, Upload } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { CanAct } from '@/session/CanAct';

/**
 * Пустой раздел: «Загрузите прайс по шаблону — карточки появятся здесь» и три шага с кнопками
 * (скачать шаблон → заполнить → загрузить), как у кабинетов Ozon и Wildberries при первом входе.
 */
export function EmptySteps({ onTemplate, onUpload }: { onTemplate: () => void; onUpload: () => void }) {
  const { t } = useTranslation();
  return (
    <section aria-labelledby="empty-products" className="flex flex-col gap-6 rounded-2xl border border-dashed border-border bg-muted/60 px-4 py-8 sm:px-8">
      <div className="flex flex-col items-center gap-2 text-center">
        <div className="flex size-12 items-center justify-center rounded-2xl bg-accent text-primary">
          <PackageOpen className="size-6" aria-hidden="true" />
        </div>
        <h2 id="empty-products" className="text-base font-semibold">
          {t('partner.empty.title')}
        </h2>
        <p className="max-w-xl text-sm text-muted-foreground">{t('partner.empty.text')}</p>
      </div>
      <ol aria-label={t('partner.empty.stepsLabel')} className="grid gap-3 md:grid-cols-3">
        <Step number={1} title={t('partner.empty.step1Title')} text={t('partner.empty.step1Text')}>
          <Button type="button" variant="outline" size="sm" onClick={onTemplate}>
            <Download aria-hidden="true" />
            {t('partner.downloadTemplate')}
          </Button>
        </Step>
        <Step number={2} title={t('partner.empty.step2Title')} text={t('partner.empty.step2Text')}>
          <FileSpreadsheet className="size-5 text-muted-foreground" aria-hidden="true" />
        </Step>
        <Step number={3} title={t('partner.empty.step3Title')} text={t('partner.empty.step3Text')}>
          <CanAct>
            <Button type="button" size="sm" onClick={onUpload}>
              <Upload aria-hidden="true" />
              {t('partner.uploadPrice')}
            </Button>
          </CanAct>
        </Step>
      </ol>
    </section>
  );
}

function Step({ number, title, text, children }: { number: number; title: string; text: string; children: React.ReactNode }) {
  return (
    <li className="flex flex-col items-start gap-2 rounded-xl border bg-card p-4">
      <span className="flex size-7 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground" aria-hidden="true">
        {number}
      </span>
      <h3 className="text-sm font-semibold">
        <span className="sr-only">{number}. </span>
        {title}
      </h3>
      <p className="text-sm text-muted-foreground">{text}</p>
      <div className="mt-auto pt-1">{children}</div>
    </li>
  );
}
