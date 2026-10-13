/**
 * Роль компании на платформе: что есть сейчас и как запросить недостающее.
 *
 * Операторская страница модерации заявок на роль работала, а подать заявку было НЕОТКУДА —
 * половина цикла существовала без второй (аудит UI 2026-07-30, §3.2). Компания, желающая
 * начать продавать, не могла об этом попросить.
 *
 * Форма — вторая половина уже существующего цикла, поэтому она устроена по тому же образцу,
 * что у B2B-маркетплейсов: заявитель видит собственную заявку в состоянии «На рассмотрении»
 * и понимает, КОГО он ждёт, а не отправляет запрос в пустоту.
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { BadgeCheck, Loader2, Send } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Input } from '@/components/ui/input';
import {
  useCompanyTypes,
  useCreateRoleApplication,
  useRoleApplications,
  useUpdateRoleApplication,
} from '@/hooks/useAccounts';
import { useUserStore } from '@/store/userStore';
import { translateApiError } from '@/lib/apiError';
import { companyTypeLabelKey } from '@/lib/codes';

/** Роли, которые компания может запросить: CLIENT выдаётся при регистрации автоматически. */
const REQUESTABLE_CODES = ['SUPPLIER', 'MANUFACTURER'];

/** Заявка ещё в работе — повторную по той же роли подавать незачем. */
const OPEN_STATUSES = ['PENDING', 'DOCUMENTS_REQUIRED', 'PAYMENT_REQUIRED'];

/**
 * Какие документы сервер требует для роли (`accounts/services/applications.py`).
 *
 * Форма их НЕ СПРАШИВАЛА: заявка уходила пустой (`contract_file:null, nda_file:null`), а
 * одобрить её было нельзя — `approve` отбивал `ROLE_APPLICATION_MISSING_CONTRACT_NDA`. Путь
 * замыкался в тупик: оператор видел заявку, которую невозможно провести.
 */
const REQUIRED_DOCS: Record<string, { field: 'contract_file' | 'nda_file' | 'partnership_agreement'; labelKey: string }[]> = {
  SUPPLIER: [
    { field: 'contract_file', labelKey: 'companyRole.docs.contract' },
    { field: 'nda_file', labelKey: 'companyRole.docs.nda' },
  ],
  MANUFACTURER: [{ field: 'partnership_agreement', labelKey: 'companyRole.docs.partnership' }],
};

export function CompanyRoleSection() {
  const { t } = useTranslation();
  const companyId = useUserStore((state) => state.company.id);
  const statusEntries = useUserStore((state) => state.company.statusEntries);

  const { data: types, isLoading: typesLoading } = useCompanyTypes();
  // Список сужен сервером до собственной компании — чужие заявки сюда не попадают.
  const { data: applications, isLoading } = useRoleApplications();
  const create = useCreateRoleApplication();
  const updateApplication = useUpdateRoleApplication();
  const [requestedType, setRequestedType] = useState<string>('');
  const [files, setFiles] = useState<Record<string, File | null>>({});

  const own = useMemo(
    () => (applications ?? []).filter((app) => app.company === companyId),
    [applications, companyId],
  );
  const openApplication = own.find((app) => OPEN_STATUSES.includes(app.status));
  const lastDecision = own.find((app) => app.status === 'APPROVED' || app.status === 'REJECTED');

  // Контекст в сторе и код типа компании — разные словари (BUYER↔CLIENT, SELLER↔SUPPLIER).
  // Переводим один раз здесь, чтобы дальше сравнивать коды с кодами.
  const CONTEXT_TO_TYPE: Record<string, string> = { BUYER: 'CLIENT', SELLER: 'SUPPLIER', MANUFACTURER: 'MANUFACTURER' };
  const ownedCodes = new Set(statusEntries.map((entry) => CONTEXT_TO_TYPE[entry.status] ?? entry.status));
  const options = (types ?? []).filter(
    (type) =>
      REQUESTABLE_CODES.includes(type.code) &&
      !ownedCodes.has(type.code) &&
      openApplication?.requested_type_code !== type.code,
  );

  const selectedCode = (types ?? []).find((type) => String(type.id) === requestedType)?.code ?? '';
  const requiredDocs = REQUIRED_DOCS[selectedCode] ?? [];
  const docsReady = requiredDocs.every((doc) => files[doc.field]);

  const submit = async () => {
    if (!companyId || !requestedType || !docsReady) return;
    try {
      await create.mutateAsync({
        company: companyId,
        requested_type: Number(requestedType),
        contract_file: files.contract_file ?? null,
        nda_file: files.nda_file ?? null,
        partnership_agreement: files.partnership_agreement ?? null,
      });
      setRequestedType('');
      setFiles({});
      toast.success(t('companyRole.submitted'));
    } catch (err) {
      toast.error(translateApiError(err));
    }
  };

  // Оператор попросил недостающее — приложить его надо ЗДЕСЬ ЖЕ, иначе статус «нужны
  // документы» остаётся тупиком: попросили, а положить некуда.
  const openDocs = REQUIRED_DOCS[openApplication?.requested_type_code ?? ''] ?? [];
  const missingForOpen = openDocs.filter(
    (doc) => !(openApplication as unknown as Record<string, unknown> | undefined)?.[doc.field],
  );

  const uploadMissing = async () => {
    if (!openApplication?.id) return;
    try {
      await updateApplication.mutateAsync({
        id: openApplication.id,
        data: {
          contract_file: files.contract_file ?? null,
          nda_file: files.nda_file ?? null,
          partnership_agreement: files.partnership_agreement ?? null,
        },
      });
      setFiles({});
      toast.success(t('companyRole.docsUploaded'));
    } catch (err) {
      toast.error(translateApiError(err));
    }
  };

  const docInput = (field: string, labelKey: string) => (
    <div key={field} className="space-y-1">
      <Label htmlFor={`role-doc-${field}`} className="text-xs">
        {t(labelKey)}
      </Label>
      <Input
        id={`role-doc-${field}`}
        type="file"
        accept=".pdf,.jpg,.jpeg,.png,.doc,.docx"
        onChange={(event) => setFiles((prev) => ({ ...prev, [field]: event.target.files?.[0] ?? null }))}
      />
    </div>
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t('companyRole.title')}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <Label>{t('companyRole.current')}</Label>
          <div className="mt-1 flex flex-wrap gap-1">
            {statusEntries.length === 0 ? (
              <span className="text-sm text-muted-foreground">—</span>
            ) : (
              statusEntries.map((entry) => (
                <Badge key={entry.status} variant="secondary">
                  {t(companyTypeLabelKey(CONTEXT_TO_TYPE[entry.status] ?? entry.status))}
                </Badge>
              ))
            )}
          </div>
        </div>

        {isLoading || typesLoading ? (
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" aria-hidden="true" />
        ) : openApplication ? (
          /* Заявитель видит собственную заявку и понимает, кого ждёт: без этого отправка
             выглядит как исчезновение запроса. */
          <div className="rounded-md border border-warning/30 bg-warning/5 p-3">
            <p className="text-sm font-medium text-foreground">
              {t('companyRole.pending', {
                role: t(companyTypeLabelKey(openApplication.requested_type_code)),
              })}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">{t('companyRole.pendingHint')}</p>
            {openApplication.status === 'DOCUMENTS_REQUIRED' ? (
              <div className="mt-3 space-y-3 border-t pt-3">
                <p className="text-xs font-medium text-foreground">
                  {openApplication.review_notes
                    ? t('companyRole.docsRequestedWithReason', { reason: openApplication.review_notes })
                    : t('companyRole.docsRequested')}
                </p>
                {missingForOpen.map((doc) => docInput(doc.field, doc.labelKey))}
                <Button
                  size="sm"
                  onClick={uploadMissing}
                  disabled={updateApplication.isPending || !missingForOpen.every((doc) => files[doc.field])}
                >
                  {t('companyRole.uploadDocs')}
                </Button>
              </div>
            ) : null}
          </div>
        ) : null}

        {!openApplication && lastDecision?.status === 'REJECTED' ? (
          <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            {lastDecision.review_notes
              ? t('companyRole.rejectedWithReason', { reason: lastDecision.review_notes })
              : t('companyRole.rejected')}
          </div>
        ) : null}

        {/* Пока справочник ролей не приехал, «все роли выданы» — неправда: это утверждение
            о состоянии компании, а не о состоянии загрузки (класс, закрытый волной U2). */}
        {typesLoading ? null : options.length > 0 ? (
          <div className="flex flex-col gap-3">
            <div className="flex-1">
              <Label htmlFor="requested-role">{t('companyRole.requestLabel')}</Label>
              <Select value={requestedType} onValueChange={setRequestedType}>
                <SelectTrigger id="requested-role" className="mt-1">
                  <SelectValue placeholder={t('companyRole.requestPlaceholder')} />
                </SelectTrigger>
                <SelectContent>
                  {options.map((type) => (
                    <SelectItem key={type.id} value={String(type.id)}>
                      {t(companyTypeLabelKey(type.code))}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {/* Документы спрашиваем сразу: сервер без них заявку не одобрит, и без формы она
                уходила заведомо непроводимой. */}
            {requiredDocs.map((doc) => docInput(doc.field, doc.labelKey))}
            <Button onClick={submit} disabled={!requestedType || !docsReady || create.isPending}>
              {create.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <Send className="mr-2 h-4 w-4" aria-hidden="true" />
              )}
              {t('companyRole.submit')}
            </Button>
          </div>
        ) : !openApplication ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <BadgeCheck className="h-4 w-4 text-success" aria-hidden="true" />
            {t('companyRole.allRolesGranted')}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
