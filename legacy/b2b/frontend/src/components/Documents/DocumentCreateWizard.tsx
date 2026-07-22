import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  ArrowLeft, ArrowRight, FileSignature, FileText, Loader2, Mail, Receipt, ScrollText, Wallet,
} from 'lucide-react';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { NewQuoteDialog } from '@/components/CRM/NewQuoteDialog';
import { RecordPaymentDialog } from '@/components/Billing/RecordPaymentDialog';
import { useDocumentTemplates, useGenerateDocument } from '@/hooks/useDocuments';
import { useDeals, useContacts } from '@/hooks/useCRM';
import { useUserStore } from '@/store/userStore';
import { translateApiError } from '@/lib/apiError';
import type { DocumentTemplate } from '@/api/documentsApi';

interface DocumentCreateWizardProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** F2 II-3: when opened from a deal card, the deal is pre-selected and its picker is locked,
   *  so the letter is bound to that deal without the user re-choosing it. */
  defaultDealId?: number;
}

/** The document kinds the wizard can start. Existing flows (quote/invoice/act/payment) are
 * ROUTED to their canonical creators — only the free-form «letter» document is built inline. */
type DocType = 'letter' | 'quote' | 'invoice' | 'act' | 'payment';

/** Wizard steps. `type` is the type picker; `letter` is the inline generate flow; the two
 * `*Hint` steps explain where invoices/acts actually come from (a route, never a dead-end). */
type Step = 'type' | 'letter' | 'invoiceHint' | 'actHint';

const NONE = '__none__';

/**
 * Wave A3 — the «Создать документ» wizard.
 *
 * Benchmark: Odoo / Bitrix24 open a single «+ Create» on the documents list, ask for the
 * document TYPE, then drop the user into the right flow for that type. We mirror that: the
 * wizard is a router first (pick a type) and an inline builder only for the genuinely new
 * free-form «letter / arbitrary document» path. КП / invoice / act / payment reuse the
 * existing creators rather than re-implementing them.
 */
export function DocumentCreateWizard({ open, onOpenChange, defaultDealId }: DocumentCreateWizardProps) {
  const { t } = useTranslation();
  // Gate document types on the member's CAPABILITIES, not the display context: `activeStatus`
  // defaults to BUYER (the manual context switcher was retired, ADR-0005), so a seller opening the
  // hub would otherwise never see КП/инвойс/акт. A dual-capability company sees both sides.
  const canSell = useUserStore((s) => s.capabilities.can_sell);
  const canBuy = useUserStore((s) => s.capabilities.can_buy);

  const [step, setStep] = useState<Step>('type');
  // The КП and payment flows hand off to a dedicated dialog rendered alongside the wizard.
  const [quoteOpen, setQuoteOpen] = useState(false);
  const [paymentOpen, setPaymentOpen] = useState(false);

  // Inline «letter» state. When opened from a deal card the deal is pre-selected and locked.
  const [templateId, setTemplateId] = useState<string>('');
  const [dealId, setDealId] = useState<string>(defaultDealId ? String(defaultDealId) : NONE);
  const [contactId, setContactId] = useState<string>(NONE);
  const [title, setTitle] = useState('');
  const dealLocked = defaultDealId != null;

  const { data: templates, isLoading: templatesLoading } = useDocumentTemplates();
  const { data: deals } = useDeals();
  const { data: contacts } = useContacts();
  const generate = useGenerateDocument();

  const templateList = useMemo<DocumentTemplate[]>(() => templates ?? [], [templates]);
  const ownedTemplates = templateList.filter((tpl) => tpl.is_owned);
  const selectedTemplate = templateList.find((tpl) => String(tpl.id) === templateId) ?? null;
  const hasOwnTemplates = ownedTemplates.length > 0;

  const busy = generate.isPending;

  function resetLetter() {
    setTemplateId('');
    setDealId(defaultDealId ? String(defaultDealId) : NONE);
    setContactId(NONE);
    setTitle('');
  }

  function closeWizard() {
    onOpenChange(false);
    // Defer reset until the dialog has visually closed to avoid a flash of step 1.
    setStep('type');
    resetLetter();
  }

  function pickType(type: DocType) {
    switch (type) {
      case 'letter':
        setStep('letter');
        break;
      case 'quote':
        // Real one-click КП creation — hand off to the seller's «Новый КП» dialog.
        onOpenChange(false);
        setQuoteOpen(true);
        break;
      case 'invoice':
        setStep('invoiceHint');
        break;
      case 'act':
        setStep('actHint');
        break;
      case 'payment':
        onOpenChange(false);
        setPaymentOpen(true);
        break;
    }
  }

  async function submitLetter() {
    if (!selectedTemplate) return;
    try {
      await generate.mutateAsync({
        template_id: selectedTemplate.id,
        deal_id: dealId !== NONE ? Number(dealId) : undefined,
        contact_id: contactId !== NONE ? Number(contactId) : undefined,
        title: title.trim() || undefined,
      });
      toast.success(t('documentsHub.success'));
      closeWizard();
      // Opened from a deal card → stay on the deal (its «Документы сделки» block refreshes via the
      // query invalidation). Standalone → jump to the registry so the new document is visible.
      if (!dealLocked) window.location.hash = 'other-documents';
    } catch (error) {
      toast.error(translateApiError(error));
    }
  }

  const typeOptions: Array<{
    type: DocType; icon: React.ReactNode; label: string; hint: string; show: boolean;
  }> = [
    {
      type: 'letter', icon: <Mail className="h-5 w-5" aria-hidden="true" />,
      label: t('documentsHub.types.letter'), hint: t('documentsHub.types.letterHint'), show: true,
    },
    {
      type: 'quote', icon: <FileText className="h-5 w-5" aria-hidden="true" />,
      label: t('documentsHub.types.quote'), hint: t('documentsHub.types.quoteHint'), show: canSell,
    },
    {
      type: 'invoice', icon: <Receipt className="h-5 w-5" aria-hidden="true" />,
      label: t('documentsHub.types.invoice'), hint: t('documentsHub.types.invoiceHint'), show: canSell,
    },
    {
      type: 'act', icon: <ScrollText className="h-5 w-5" aria-hidden="true" />,
      label: t('documentsHub.types.act'), hint: t('documentsHub.types.actHint'), show: canSell,
    },
    {
      type: 'payment', icon: <Wallet className="h-5 w-5" aria-hidden="true" />,
      label: t('documentsHub.types.payment'), hint: t('documentsHub.types.paymentHint'), show: canBuy,
    },
  ];

  return (
    <>
      <Dialog open={open} onOpenChange={(next) => { if (!busy) { if (next) onOpenChange(true); else closeWizard(); } }}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <FileSignature className="h-5 w-5" aria-hidden="true" />
              {step === 'type' ? t('documentsHub.create') : t('documentsHub.steps.letterTitle')}
            </DialogTitle>
            <DialogDescription>
              {step === 'type' ? t('documentsHub.steps.typeDescription') : t('documentsHub.steps.letterDescription')}
            </DialogDescription>
          </DialogHeader>

          {step === 'type' && (
            <div className="mt-2 space-y-2">
              {typeOptions.filter((o) => o.show).map((option) => (
                <Button
                  key={option.type}
                  type="button"
                  variant="outline"
                  className="h-auto w-full justify-start gap-3 whitespace-normal py-3 text-left"
                  onClick={() => pickType(option.type)}
                >
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                    {option.icon}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2 font-medium">{option.label}</span>
                    <span className="mt-0.5 block text-xs font-normal text-muted-foreground">{option.hint}</span>
                  </span>
                  <ArrowRight className="h-4 w-4 shrink-0 opacity-50" aria-hidden="true" />
                </Button>
              ))}
            </div>
          )}

          {step === 'letter' && (
            <div className="mt-2 space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="doc-wizard-template">{t('documentsHub.selectTemplate')}</Label>
                <Select value={templateId || undefined} onValueChange={setTemplateId} disabled={busy}>
                  <SelectTrigger id="doc-wizard-template">
                    <SelectValue
                      placeholder={templatesLoading ? t('common.loading') : t('documentsHub.selectTemplatePlaceholder')}
                    />
                  </SelectTrigger>
                  <SelectContent>
                    {templateList.length === 0 ? (
                      <div className="px-2 py-3 text-xs text-muted-foreground">{t('documentsHub.noTemplates')}</div>
                    ) : (
                      templateList.map((tpl) => (
                        <SelectItem key={tpl.id} value={String(tpl.id)}>
                          <span className="flex items-center gap-2">
                            {tpl.name}
                            {!tpl.is_owned && (
                              <Badge variant="secondary" className="text-xs">{t('documentsHub.sample')}</Badge>
                            )}
                          </span>
                        </SelectItem>
                      ))
                    )}
                  </SelectContent>
                </Select>
                {selectedTemplate && !selectedTemplate.is_owned && (
                  <p className="text-xs text-muted-foreground">{t('documentsHub.sampleHint')}</p>
                )}
                {!hasOwnTemplates && templateList.length > 0 && (
                  <p className="text-xs text-muted-foreground">{t('documentsHub.noOwnTemplatesHint')}</p>
                )}
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="doc-wizard-title">{t('documentsHub.titleField')}</Label>
                <Input
                  id="doc-wizard-title"
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  placeholder={selectedTemplate?.name || t('documentsHub.titlePlaceholder')}
                  maxLength={255}
                  disabled={busy}
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="doc-wizard-deal">{t('documentsHub.dealOptional')}</Label>
                  {dealLocked ? (
                    // Opened from a deal card — the deal is fixed, show it read-only.
                    <div
                      id="doc-wizard-deal"
                      className="flex h-9 items-center rounded-md border border-input bg-muted/40 px-3 text-sm text-foreground"
                    >
                      {(deals ?? []).find((deal) => String(deal.id) === dealId)?.title || `#${dealId}`}
                    </div>
                  ) : (
                    <Select value={dealId} onValueChange={setDealId} disabled={busy}>
                      <SelectTrigger id="doc-wizard-deal">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={NONE}>{t('documentsHub.noContext')}</SelectItem>
                        {(deals ?? []).map((deal) => (
                          <SelectItem key={deal.id} value={String(deal.id)}>
                            {deal.title || `#${deal.id}`}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="doc-wizard-contact">{t('documentsHub.contactOptional')}</Label>
                  <Select value={contactId} onValueChange={setContactId} disabled={busy}>
                    <SelectTrigger id="doc-wizard-contact">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={NONE}>{t('documentsHub.noContext')}</SelectItem>
                      {(contacts ?? []).map((contact) => (
                        <SelectItem key={contact.id} value={String(contact.id)}>
                          {contact.company_name ? `${contact.company_name} — ${contact.name}` : contact.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <p className="text-xs text-muted-foreground">{t('documentsHub.contextHint')}</p>
            </div>
          )}

          {step === 'invoiceHint' && (
            <HintPanel
              icon={<Receipt className="h-6 w-6 text-primary" aria-hidden="true" />}
              text={t('documentsHub.hints.invoice')}
            />
          )}
          {step === 'actHint' && (
            <HintPanel
              icon={<ScrollText className="h-6 w-6 text-primary" aria-hidden="true" />}
              text={t('documentsHub.hints.act')}
            />
          )}

          <DialogFooter className="mt-4 gap-2">
            {step !== 'type' && (
              <Button type="button" variant="ghost" onClick={() => setStep('type')} disabled={busy}>
                <ArrowLeft className="mr-1 h-4 w-4" aria-hidden="true" />
                {t('common.back')}
              </Button>
            )}
            {step === 'letter' && (
              <Button type="button" onClick={submitLetter} disabled={busy || !selectedTemplate}>
                {busy && <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden="true" />}
                {busy ? t('documentsHub.generating') : t('documentsHub.generate')}
              </Button>
            )}
            {step === 'invoiceHint' && (
              <Button type="button" onClick={() => { closeWizard(); window.location.hash = 'contracts'; }}>
                {t('documentsHub.hints.goToContracts')}
              </Button>
            )}
            {step === 'actHint' && (
              <Button type="button" onClick={() => { closeWizard(); window.location.hash = 'invoices'; }}>
                {t('documentsHub.hints.goToInvoices')}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <NewQuoteDialog
        open={quoteOpen}
        onOpenChange={setQuoteOpen}
        onCreated={(newDealId) => { window.location.hash = `deal-quote/${newDealId}`; }}
      />
      <RecordPaymentDialog open={paymentOpen} onOpenChange={setPaymentOpen} />
    </>
  );
}

function HintPanel({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <div className="mt-2 flex items-start gap-3 rounded-md border border-border bg-muted/30 p-4">
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-primary/10">{icon}</span>
      <p className="text-sm leading-relaxed text-foreground">{text}</p>
    </div>
  );
}

export default DocumentCreateWizard;
