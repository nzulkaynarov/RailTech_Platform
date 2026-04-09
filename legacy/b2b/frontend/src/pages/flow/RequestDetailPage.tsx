/**
 * RequestDetailPage — Multi-perspective request detail
 *
 * Adapts to activeStatus:
 *  - BUYER:        sees own request status, imported items, КП when ready
 *  - SELLER:       sees incoming request, availability, RFQ management, cost calc
 *  - MANUFACTURER: sees RFQ items, enters prices + lead times, confirms
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ArrowLeft, CheckCircle2, AlertCircle, HelpCircle,
  Send, Calculator, Package, Clock, DollarSign, Factory,
  ThumbsUp, ThumbsDown, ChevronRight, RotateCcw, Check,
  Eye, PanelRightClose, PanelRightOpen,
} from 'lucide-react';
import { DealChatPanel } from '@/components/Sourcing/DealChatPanel';
import { QuoteBuilderGrid } from '@/components/Sourcing/QuoteBuilderGrid';

import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip as RechartsTooltip, ResponsiveContainer, Cell,
} from 'recharts';
import { cn } from '@/lib/utils';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from '@/components/ui/dialog';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Progress } from '@/components/ui/progress';
import { Textarea } from '@/components/ui/textarea';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';

import { useUserStore } from '@/store/userStore';
import { useCurrencyStore } from '@/store/currencyStore';
import {
  useFlowStore,
  requestStatusLabels,
  requestStatusColors,
  dealStageLabels,
  dealStageColors,
  type RequestItem,
  type MatchStatus,
} from '@/store/flowStore';

/* ─── Helpers ────────────────────────────────────────────────────────── */

function MatchBadge({ status }: { status: MatchStatus }) {
  const { t } = useTranslation();
  const map: Record<MatchStatus, { label: string; className: string; icon: React.ReactNode }> = {
    matched: { label: t('requestDetail.matchStatus.matched'), className: 'bg-primary/10 text-primary border-primary/20', icon: <CheckCircle2 className="h-3 w-3" /> },
    partial: { label: t('requestDetail.matchStatus.partial'), className: 'bg-muted text-muted-foreground border-border', icon: <HelpCircle className="h-3 w-3" /> },
    not_found: { label: t('requestDetail.matchStatus.notFound'), className: 'bg-destructive/10 text-destructive border-destructive/20', icon: <AlertCircle className="h-3 w-3" /> },
  };
  const m = map[status];
  return (
    <Badge variant="outline" className={cn('gap-1 text-xs', m.className)}>
      {m.icon} {m.label}
    </Badge>
  );
}

function StatusBadge({ status }: { status: string; colors?: string }) {
  const { t } = useTranslation();
  const labelKey = requestStatusLabels[status as keyof typeof requestStatusLabels];
  return (
    <Badge variant="outline" className={cn('text-xs', requestStatusColors[status as keyof typeof requestStatusColors])}>
      {labelKey ? t(labelKey) : status}
    </Badge>
  );
}

function StepIndicator({ steps, current }: { steps: string[]; current: number }) {
  return (
    <div className="flex items-center gap-1">
      {steps.map((step, i) => (
        <div key={step} className="flex items-center gap-1">
          <div className={cn(
            'flex h-6 min-w-6 items-center justify-center rounded-full text-xs font-medium px-1.5',
            i < current ? 'bg-primary text-primary-foreground' :
            i === current ? 'bg-primary text-primary-foreground ring-2 ring-primary/30' :
            'bg-muted text-muted-foreground'
          )}>
            {i < current ? <Check className="h-3 w-3" /> : i + 1}
          </div>
          <span className={cn('text-xs hidden sm:inline', i === current ? 'font-medium' : 'text-muted-foreground')}>
            {step}
          </span>
          {i < steps.length - 1 && <ChevronRight className="h-3 w-3 text-muted-foreground" />}
        </div>
      ))}
    </div>
  );
}

function formatCurrency(val: number | undefined): string {
  if (val == null) return '—';
  return useCurrencyStore.getState().format(val);
}

/* ─── Props ──────────────────────────────────────────────────────────── */

interface RequestDetailPageProps {
  onBack: () => void;
  onNavigate: (target: string) => void;
}

/* ═══════════════════════════════════════════════════════════════════════
   MAIN COMPONENT
   ═══════════════════════════════════════════════════════════════════════ */

export function RequestDetailPage({ onBack, onNavigate }: RequestDetailPageProps) {
  const { activeStatus } = useUserStore();

  switch (activeStatus) {
    case 'BUYER':
      return <BuyerView onBack={onBack} onNavigate={onNavigate} />;
    case 'SELLER':
      return <SellerView onBack={onBack} onNavigate={onNavigate} />;
    case 'MANUFACTURER':
      return <ManufacturerView onBack={onBack} />;
    default:
      return <SellerView onBack={onBack} onNavigate={onNavigate} />;
  }
}

/* ═══════════════════════════════════════════════════════════════════════
   BUYER VIEW — Client sees their request + КП
   ═══════════════════════════════════════════════════════════════════════ */

function BuyerView({ onBack }: { onBack: () => void; onNavigate: (t: string) => void }) {
  const { t } = useTranslation();
  const { request, deal, clientAcceptKP, clientRejectKP, resetFlow } = useFlowStore();
  const [rejectDialog, setRejectDialog] = useState(false);
  const [rejectReason, setRejectReason] = useState('');
  const [rejectComment, setRejectComment] = useState('');
  const [negotiateDialog, setNegotiateDialog] = useState(false);
  const [negotiateDiscount, setNegotiateDiscount] = useState('5');
  const [negotiateComment, setNegotiateComment] = useState('');
  const [negotiateSent, setNegotiateSent] = useState(false);

  const matched = request.items.filter((i) => i.matchStatus === 'matched').length;
  const partial = request.items.filter((i) => i.matchStatus === 'partial').length;
  const notFound = request.items.filter((i) => i.matchStatus === 'not_found').length;
  const hasKP = ['kp_sent', 'kp_review', 'kp_accepted', 'kp_rejected', 'deal_opened'].includes(request.status);
  const kpItems = request.items.filter((i) => i.finalPrice != null);
  const totalNoVAT = kpItems.reduce((s, i) => s + (i.finalPrice ?? 0) * i.quantity, 0);
  const totalWithVAT = kpItems.reduce((s, i) => s + (i.finalPriceWithVAT ?? 0) * i.quantity, 0);

  const stepIndex =
    request.status === 'submitted' ? 0 :
    ['processing', 'rfq_sent', 'rfq_received', 'calculating'].includes(request.status) ? 1 :
    ['kp_sent', 'kp_review'].includes(request.status) ? 2 :
    ['kp_accepted', 'deal_opened'].includes(request.status) ? 3 : 2;

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="icon" onClick={onBack}><ArrowLeft className="h-4 w-4" /></Button>
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold">{t('requestDetail.title', { number: request.number })}</h1>
            <StatusBadge status={request.status} />
          </div>
          <p className="text-sm text-muted-foreground mt-0.5">
            {t('requestDetail.importSummary', { count: request.items.length, date: request.createdAt })}
          </p>
        </div>
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="outline" size="sm" className="gap-2" onClick={resetFlow}>
                <RotateCcw className="h-3.5 w-3.5" /> {t('requestDetail.resetDemo')}
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              <p>{t('requestDetail.resetDemoHint')}</p>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>

      {/* Progress steps */}
      <Card className="py-3">
        <CardContent className="px-4">
          <StepIndicator
            steps={[
              t('requestDetail.steps.submitted'),
              t('requestDetail.steps.supplierProcessing'),
              t('requestDetail.steps.quoteReceived'),
              t('requestDetail.steps.deal'),
            ]}
            current={stepIndex}
          />
        </CardContent>
      </Card>

      {/* Import summary */}
      <div className="grid grid-cols-3 gap-4">
        <Card className="py-4 gap-1">
          <CardContent className="px-4 flex items-center gap-3">
            <div className="rounded-lg bg-primary/10 p-2"><CheckCircle2 className="h-5 w-5 text-primary" /></div>
            <div><p className="text-2xl font-bold">{matched}</p><p className="text-xs text-muted-foreground">{t('requestDetail.stats.matched')}</p></div>
          </CardContent>
        </Card>
        <Card className="py-4 gap-1">
          <CardContent className="px-4 flex items-center gap-3">
            <div className="rounded-lg bg-muted p-2"><HelpCircle className="h-5 w-5 text-muted-foreground" /></div>
            <div><p className="text-2xl font-bold">{partial}</p><p className="text-xs text-muted-foreground">{t('requestDetail.stats.partial')}</p></div>
          </CardContent>
        </Card>
        <Card className="py-4 gap-1">
          <CardContent className="px-4 flex items-center gap-3">
            <div className="rounded-lg bg-destructive/10 p-2"><AlertCircle className="h-5 w-5 text-destructive" /></div>
            <div><p className="text-2xl font-bold">{notFound}</p><p className="text-xs text-muted-foreground">{t('requestDetail.stats.notFound')}</p></div>
          </CardContent>
        </Card>
      </div>

      <Tabs defaultValue={hasKP ? 'kp' : 'items'}>
        <TabsList>
          <TabsTrigger value="items">{t('requestDetail.tabs.items', { count: request.items.length })}</TabsTrigger>
          {hasKP && <TabsTrigger value="kp">{t('requestDetail.tabs.quote')}</TabsTrigger>}
          {deal && <TabsTrigger value="deal">{t('requestDetail.tabs.deal')}</TabsTrigger>}
        </TabsList>

        {/* Items list */}
        <TabsContent value="items">
          <Card className="py-0 gap-0 overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/40">
                  <TableHead className="w-8">#</TableHead>
                  <TableHead>{t('requestDetail.table.name')}</TableHead>
                  <TableHead>{t('requestDetail.table.article')}</TableHead>
                  <TableHead>{t('requestDetail.table.gost')}</TableHead>
                  <TableHead>{t('requestDetail.table.unit')}</TableHead>
                  <TableHead className="text-right">{t('requestDetail.table.quantity')}</TableHead>
                  <TableHead>{t('requestDetail.table.status')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {request.items.map((item, idx) => (
                  <TableRow key={item.id}>
                    <TableCell className="text-muted-foreground text-xs">{idx + 1}</TableCell>
                    <TableCell className="font-medium text-sm">{item.name}</TableCell>
                    <TableCell className="font-mono text-xs text-primary">{item.article}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{item.gost}</TableCell>
                    <TableCell className="text-sm">{item.uom}</TableCell>
                    <TableCell className="text-right font-medium tabular-nums">{item.quantity}</TableCell>
                    <TableCell><MatchBadge status={item.matchStatus} /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
        </TabsContent>

        {/* КП view */}
        {hasKP && (
          <TabsContent value="kp">
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle className="text-base">{t('requestDetail.quoteFrom', { seller: request.sellerName })}</CardTitle>
                    <CardDescription>{t('requestDetail.quoteItemsSummary', { count: kpItems.length, date: request.updatedAt })}</CardDescription>
                  </div>
                  {request.status === 'kp_sent' && !negotiateSent && (
                    <div className="flex gap-2">
                      <Button variant="outline" className="gap-2 text-destructive" onClick={() => setRejectDialog(true)}>
                        <ThumbsDown className="h-4 w-4" /> {t('requestDetail.actions.reject')}
                      </Button>
                      <Button variant="outline" className="gap-2" onClick={() => setNegotiateDialog(true)}>
                        <DollarSign className="h-4 w-4" /> {t('requestDetail.actions.requestDiscount')}
                      </Button>
                      <Button className="gap-2" onClick={clientAcceptKP}>
                        <ThumbsUp className="h-4 w-4" /> {t('requestDetail.actions.acceptQuote')}
                      </Button>
                    </div>
                  )}
                  {request.status === 'kp_sent' && negotiateSent && (
                    <div className="flex items-center gap-3">
                      <Badge className="bg-muted text-muted-foreground text-sm px-3 py-1">{t('requestDetail.status.discountRequested')}</Badge>
                      <Button className="gap-2" onClick={clientAcceptKP}>
                        <ThumbsUp className="h-4 w-4" /> {t('requestDetail.actions.acceptCurrentQuote')}
                      </Button>
                    </div>
                  )}
                  {request.status === 'kp_accepted' && (
                    <Badge className="bg-primary/10 text-primary text-sm px-3 py-1">{t('requestDetail.status.accepted')}</Badge>
                  )}
                  {request.status === 'kp_rejected' && (
                    <Badge className="bg-destructive/10 text-destructive text-sm px-3 py-1">{t('requestDetail.status.rejected')}</Badge>
                  )}
                </div>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow className="bg-muted/40">
                      <TableHead>{t('requestDetail.table.name')}</TableHead>
                      <TableHead>{t('requestDetail.table.unit')}</TableHead>
                      <TableHead className="text-right">{t('requestDetail.table.quantity')}</TableHead>
                      <TableHead className="text-right">{t('requestDetail.table.priceExclVAT')}</TableHead>
                      <TableHead className="text-right">{t('requestDetail.table.priceInclVAT')}</TableHead>
                      <TableHead className="text-right">{t('requestDetail.table.totalInclVAT')}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {kpItems.map((item) => (
                      <TableRow key={item.id}>
                        <TableCell className="font-medium text-sm">{item.name}</TableCell>
                        <TableCell>{item.uom}</TableCell>
                        <TableCell className="text-right tabular-nums">{item.quantity}</TableCell>
                        <TableCell className="text-right tabular-nums">{formatCurrency(item.finalPrice)}</TableCell>
                        <TableCell className="text-right tabular-nums">{formatCurrency(item.finalPriceWithVAT)}</TableCell>
                        <TableCell className="text-right font-medium tabular-nums">
                          {formatCurrency((item.finalPriceWithVAT ?? 0) * item.quantity)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                <Separator className="my-4" />
                <div className="flex justify-end gap-8">
                  <div className="text-right">
                    <p className="text-xs text-muted-foreground">{t('requestDetail.totals.exclVAT')}</p>
                    <p className="text-lg font-bold tabular-nums">{formatCurrency(totalNoVAT)}</p>
                  </div>
                  <div className="text-right">
                    <p className="text-xs text-muted-foreground">{t('requestDetail.totals.vat')}</p>
                    <p className="text-lg font-bold tabular-nums">{formatCurrency(totalWithVAT - totalNoVAT)}</p>
                  </div>
                  <div className="text-right">
                    <p className="text-xs text-muted-foreground">{t('requestDetail.totals.inclVAT')}</p>
                    <p className="text-2xl font-bold tabular-nums text-primary">{formatCurrency(totalWithVAT)}</p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        )}

        {/* Deal view */}
        {deal && (
          <TabsContent value="deal">
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle className="text-base">{t('requestDetail.deal.title', { number: deal.number })}</CardTitle>
                    <CardDescription>{t('requestDetail.deal.manager', { name: deal.manager })}</CardDescription>
                  </div>
                  <Badge className={cn('text-sm px-3 py-1', dealStageColors[deal.stage])}>
                    {dealStageLabels[deal.stage]}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-3 gap-4">
                  <div className="rounded-lg border p-4">
                    <p className="text-xs text-muted-foreground">{t('requestDetail.deal.amount')}</p>
                    <p className="text-xl font-bold tabular-nums">{formatCurrency(deal.totalAmountWithVAT)}</p>
                  </div>
                  <div className="rounded-lg border p-4">
                    <p className="text-xs text-muted-foreground">{t('requestDetail.deal.items')}</p>
                    <p className="text-xl font-bold">{deal.itemCount}</p>
                  </div>
                  <div className="rounded-lg border p-4">
                    <p className="text-xs text-muted-foreground">{t('requestDetail.deal.createdAt')}</p>
                    <p className="text-xl font-bold">{deal.createdAt}</p>
                  </div>
                </div>
                <p className="text-sm text-muted-foreground">
                  {t('requestDetail.deal.nextStep', { manager: deal.manager })}
                </p>
              </CardContent>
            </Card>
          </TabsContent>
        )}
      </Tabs>

      {/* Reject dialog */}
      <Dialog open={rejectDialog} onOpenChange={setRejectDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('requestDetail.rejectDialog.title')}</DialogTitle>
            <DialogDescription>{t('requestDetail.rejectDialog.description')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label>{t('requestDetail.rejectDialog.reason')}</Label>
              <Select value={rejectReason} onValueChange={setRejectReason}>
                <SelectTrigger><SelectValue placeholder={t('requestDetail.rejectDialog.selectReason')} /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="expensive">{t('requestDetail.rejectDialog.reasons.expensive')}</SelectItem>
                  <SelectItem value="terms">{t('requestDetail.rejectDialog.reasons.terms')}</SelectItem>
                  <SelectItem value="partial">{t('requestDetail.rejectDialog.reasons.partial')}</SelectItem>
                  <SelectItem value="other">{t('requestDetail.rejectDialog.reasons.other')}</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>{t('requestDetail.rejectDialog.comment')}</Label>
              <Textarea placeholder={t('requestDetail.rejectDialog.commentPlaceholder')} value={rejectComment} onChange={(e) => setRejectComment(e.target.value)} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRejectDialog(false)}>{t('common.cancel')}</Button>
            <Button variant="destructive" disabled={!rejectReason} onClick={() => {
              clientRejectKP(rejectReason, rejectComment);
              setRejectDialog(false);
            }}>{t('requestDetail.actions.rejectQuote')}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Negotiate discount dialog */}
      <Dialog open={negotiateDialog} onOpenChange={setNegotiateDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('requestDetail.negotiateDialog.title')}</DialogTitle>
            <DialogDescription>
              {t('requestDetail.negotiateDialog.currentAmount', { amount: formatCurrency(totalWithVAT) })}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label>{t('requestDetail.negotiateDialog.desiredDiscount')}</Label>
              <div className="flex gap-2">
                {['3', '5', '10', '15'].map((d) => (
                  <Button
                    key={d}
                    variant={negotiateDiscount === d ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => setNegotiateDiscount(d)}
                  >
                    {d}%
                  </Button>
                ))}
                <Input
                  className="w-20 h-9"
                  type="number"
                  value={negotiateDiscount}
                  onChange={(e) => setNegotiateDiscount(e.target.value)}
                  min={1}
                  max={50}
                />
              </div>
              <p className="text-xs text-muted-foreground">
                {t('requestDetail.negotiateDialog.estimatedAmount', {
                  amount: formatCurrency(totalWithVAT * (1 - Number(negotiateDiscount) / 100)),
                  savings: formatCurrency(totalWithVAT * Number(negotiateDiscount) / 100),
                })}
              </p>
            </div>
            <div className="space-y-2">
              <Label>{t('requestDetail.negotiateDialog.justification')}</Label>
              <Textarea
                placeholder={t('requestDetail.negotiateDialog.justificationPlaceholder')}
                value={negotiateComment}
                onChange={(e) => setNegotiateComment(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setNegotiateDialog(false)}>{t('common.cancel')}</Button>
            <Button className="gap-2" onClick={() => {
              setNegotiateSent(true);
              setNegotiateDialog(false);
            }}>
              <Send className="h-4 w-4" /> {t('requestDetail.actions.sendRequest')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════
   SELLER VIEW — RailTech processes the request
   ═══════════════════════════════════════════════════════════════════════ */

function SellerView({ onBack }: { onBack: () => void; onNavigate: (t: string) => void }) {
  const { t } = useTranslation();
  const {
    request, sellerStartProcessing, sellerSendRFQs, manufacturerRespondAll,
    sellerCalculate, sellerSendKP, resetFlow, updateItem,
  } = useFlowStore();

  const [margin, setMargin] = useState('15');
  const [chatPanelOpen, setChatPanelOpen] = useState(true);

  const accessibleItems = request.items.filter((i) => i.sellerHasAccess);
  const inStockItems = accessibleItems.filter((i) => i.inSellerStock);
  const needRFQ = accessibleItems.filter((i) => !i.inSellerStock);
  const noAccess = request.items.filter((i) => !i.sellerHasAccess);
  const rfqResponded = needRFQ.filter((i) => i.rfqStatus === 'responded').length;

  const canSendRFQ = request.status === 'processing' && needRFQ.length > 0;
  const canCalculate = ['rfq_received', 'rfq_sent'].includes(request.status) || (request.status === 'processing' && needRFQ.length === 0);
  const canSendKP = request.status === 'calculating';

  const stepIndex =
    request.status === 'submitted' ? 0 :
    request.status === 'processing' ? 1 :
    ['rfq_sent'].includes(request.status) ? 2 :
    request.status === 'rfq_received' ? 3 :
    request.status === 'calculating' ? 4 :
    ['kp_sent', 'kp_review', 'kp_accepted', 'kp_rejected', 'deal_opened'].includes(request.status) ? 5 : 0;

  return (
    <div className="flex gap-4">
      {/* Left panel — 70% (or 100% if chat closed) */}
      <div className={cn('flex flex-col gap-6 min-w-0', chatPanelOpen ? 'flex-[7]' : 'flex-1')}>
      {/* Header */}
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="icon" onClick={onBack}><ArrowLeft className="h-4 w-4" /></Button>
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold">{t('requestDetail.title', { number: request.number })}</h1>
            <StatusBadge status={request.status} />
          </div>
          <p className="text-sm text-muted-foreground mt-0.5">
            {t('requestDetail.seller.client')}: <span className="font-medium text-foreground">{request.clientName}</span> · {t('requestDetail.seller.itemsCount', { count: request.items.length })}
          </p>
        </div>
        <Button variant="ghost" size="icon" onClick={() => setChatPanelOpen(!chatPanelOpen)}>
          {chatPanelOpen ? <PanelRightClose className="h-4 w-4" /> : <PanelRightOpen className="h-4 w-4" />}
        </Button>
        <Button variant="outline" size="sm" className="gap-2" onClick={resetFlow}>
          <RotateCcw className="h-3.5 w-3.5" /> {t('requestDetail.reset')}
        </Button>
      </div>

      {/* Steps */}
      <Card className="py-3">
        <CardContent className="px-4">
          <StepIndicator
            steps={[
              t('requestDetail.sellerSteps.received'),
              t('requestDetail.sellerSteps.analysis'),
              t('requestDetail.sellerSteps.rfqFactories'),
              t('requestDetail.sellerSteps.responses'),
              t('requestDetail.sellerSteps.calculation'),
              t('requestDetail.sellerSteps.quoteToClient'),
            ]}
            current={stepIndex}
          />
        </CardContent>
      </Card>

      {/* KPI */}
      <div className="grid grid-cols-4 gap-4">
        <Card className="py-4 gap-1">
          <CardContent className="px-4 flex items-center gap-3">
            <div className="rounded-lg bg-primary/10 p-2"><Package className="h-5 w-5 text-primary" /></div>
            <div><p className="text-2xl font-bold">{inStockItems.length}</p><p className="text-xs text-muted-foreground">{t('requestDetail.seller.inStock')}</p></div>
          </CardContent>
        </Card>
        <Card className="py-4 gap-1">
          <CardContent className="px-4 flex items-center gap-3">
            <div className="rounded-lg bg-primary/10 p-2"><Factory className="h-5 w-5 text-primary" /></div>
            <div><p className="text-2xl font-bold">{needRFQ.length}</p><p className="text-xs text-muted-foreground">{t('requestDetail.seller.needRFQ')}</p></div>
          </CardContent>
        </Card>
        <Card className="py-4 gap-1">
          <CardContent className="px-4 flex items-center gap-3">
            <div className="rounded-lg bg-muted p-2"><Clock className="h-5 w-5 text-muted-foreground" /></div>
            <div><p className="text-2xl font-bold">{rfqResponded}/{needRFQ.length}</p><p className="text-xs text-muted-foreground">{t('requestDetail.seller.factoryResponses')}</p></div>
          </CardContent>
        </Card>
        <Card className="py-4 gap-1">
          <CardContent className="px-4 flex items-center gap-3">
            <div className="rounded-lg bg-destructive/10 p-2"><AlertCircle className="h-5 w-5 text-destructive" /></div>
            <div><p className="text-2xl font-bold">{noAccess.length}</p><p className="text-xs text-muted-foreground">{t('requestDetail.seller.noAccess')}</p></div>
          </CardContent>
        </Card>
      </div>

      {/* Action buttons */}
      <div className="flex gap-2">
        {request.status === 'submitted' && (
          <Button className="gap-2" onClick={sellerStartProcessing}>
            <Eye className="h-4 w-4" /> {t('requestDetail.actions.takeInWork')}
          </Button>
        )}
        {canSendRFQ && (
          <Button className="gap-2" onClick={sellerSendRFQs}>
            <Send className="h-4 w-4" /> {t('requestDetail.actions.sendRFQ', { count: needRFQ.length })}
          </Button>
        )}
        {request.status === 'rfq_sent' && (
          <Button variant="outline" className="gap-2" onClick={manufacturerRespondAll}>
            <Clock className="h-4 w-4" /> {t('requestDetail.actions.simulateResponses')}
          </Button>
        )}
        {canCalculate && request.status === 'rfq_received' && (
          <div className="flex items-center gap-2">
            <Label className="text-sm">{t('requestDetail.seller.marginLabel')}:</Label>
            <Input className="w-20 h-9" type="number" value={margin} onChange={(e) => setMargin(e.target.value)} />
            <Button className="gap-2" onClick={() => sellerCalculate(Number(margin))}>
              <Calculator className="h-4 w-4" /> {t('requestDetail.actions.calculateCost')}
            </Button>
          </div>
        )}
        {canSendKP && (
          <Button className="gap-2" onClick={sellerSendKP}>
            <Send className="h-4 w-4" /> {t('requestDetail.actions.sendQuoteToClient')}
          </Button>
        )}
      </div>

      {/* Items table */}
      <Tabs defaultValue="all">
        <TabsList>
          <TabsTrigger value="all">{t('requestDetail.sellerTabs.all', { count: request.items.length })}</TabsTrigger>
          <TabsTrigger value="stock">{t('requestDetail.sellerTabs.inStock', { count: inStockItems.length })}</TabsTrigger>
          <TabsTrigger value="rfq">{t('requestDetail.sellerTabs.rfq', { count: needRFQ.length })}</TabsTrigger>
          <TabsTrigger value="noaccess">{t('requestDetail.sellerTabs.noAccess', { count: noAccess.length })}</TabsTrigger>
        </TabsList>

        <TabsContent value="all">
          <SellerItemsTable items={request.items} showAll />
        </TabsContent>
        <TabsContent value="stock">
          <SellerItemsTable items={inStockItems} />
        </TabsContent>
        <TabsContent value="rfq">
          <SellerItemsTable items={needRFQ} showRFQ />
        </TabsContent>
        <TabsContent value="noaccess">
          <SellerItemsTable items={noAccess} />
        </TabsContent>
      </Tabs>

      {/* Cost summary */}
      {request.status === 'calculating' || ['kp_sent', 'kp_review', 'kp_accepted', 'kp_rejected', 'deal_opened'].includes(request.status) ? (
        <>
          <CostSummaryCard items={request.items} />
          {/* Quote Builder Grid */}
          <QuoteBuilderGrid
            items={request.items}
            onUpdateMargin={(itemId, newMargin) => updateItem(itemId, { marginPercent: newMargin })}
            defaultMargin={Number(margin)}
          />
        </>
      ) : null}
      </div>{/* end left panel */}

      {/* Right panel — 30% chat */}
      {chatPanelOpen && (
        <div className="flex-[3] min-w-[280px] max-w-[380px] sticky top-0 self-start">
          <DealChatPanel />
        </div>
      )}
    </div>
  );
}

function SellerItemsTable({ items, showRFQ, showAll }: { items: RequestItem[]; showRFQ?: boolean; showAll?: boolean }) {
  const { t } = useTranslation();
  return (
    <Card className="py-0 gap-0 overflow-hidden">
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/40">
            <TableHead className="w-8">#</TableHead>
            <TableHead>{t('requestDetail.table.name')}</TableHead>
            <TableHead>{t('requestDetail.table.article')}</TableHead>
            {showAll && <TableHead>{t('requestDetail.table.status')}</TableHead>}
            <TableHead>{t('requestDetail.table.factory')}</TableHead>
            <TableHead className="text-right">{t('requestDetail.table.quantity')}</TableHead>
            <TableHead className="text-right">{t('requestDetail.table.priceFCA')}</TableHead>
            {(showRFQ || showAll) && <TableHead>{t('requestDetail.table.rfq')}</TableHead>}
            {(showRFQ || showAll) && <TableHead className="text-right">{t('requestDetail.table.factoryPrice')}</TableHead>}
            {(showRFQ || showAll) && <TableHead>{t('requestDetail.table.leadTime')}</TableHead>}
            {showAll && <TableHead className="text-right">{t('requestDetail.table.totalInclVAT')}</TableHead>}
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((item, idx) => (
            <TableRow key={item.id} className={cn(!item.sellerHasAccess && 'opacity-50')}>
              <TableCell className="text-xs text-muted-foreground">{idx + 1}</TableCell>
              <TableCell>
                <div>
                  <span className="font-medium text-sm">{item.name}</span>
                  {item.inSellerStock && (
                    <Badge variant="secondary" className="ml-1.5 text-xs px-1 py-0">{t('requestDetail.seller.warehouse')}</Badge>
                  )}
                </div>
              </TableCell>
              <TableCell className="font-mono text-xs text-primary">{item.article}</TableCell>
              {showAll && <TableCell><MatchBadge status={item.matchStatus} /></TableCell>}
              <TableCell className="text-xs">{item.manufacturerName ?? '—'}</TableCell>
              <TableCell className="text-right tabular-nums font-medium">{item.quantity}</TableCell>
              <TableCell className="text-right tabular-nums">{formatCurrency(item.partnerPriceFCA)}</TableCell>
              {(showRFQ || showAll) && (
                <TableCell>
                  {item.rfqStatus === 'not_sent' && item.sellerHasAccess && !item.inSellerStock && (
                    <Badge variant="outline" className="text-xs bg-muted">{t('requestDetail.rfqStatus.waiting')}</Badge>
                  )}
                  {item.rfqStatus === 'sent' && (
                    <Badge variant="outline" className="text-xs bg-primary/10 text-primary border-primary/20">{t('requestDetail.rfqStatus.sent')}</Badge>
                  )}
                  {item.rfqStatus === 'responded' && (
                    <Badge variant="outline" className="text-xs bg-primary/10 text-primary border-primary/20">{t('requestDetail.rfqStatus.responded')}</Badge>
                  )}
                </TableCell>
              )}
              {(showRFQ || showAll) && (
                <TableCell className="text-right tabular-nums font-medium">
                  {item.rfqPrice ? formatCurrency(item.rfqPrice) : '—'}
                </TableCell>
              )}
              {(showRFQ || showAll) && (
                <TableCell className="text-xs">
                  {item.rfqLeadDays ? t('requestDetail.seller.leadDays', { days: item.rfqLeadDays }) : '—'}
                </TableCell>
              )}
              {showAll && (
                <TableCell className="text-right tabular-nums font-medium">
                  {item.finalPriceWithVAT
                    ? formatCurrency(item.finalPriceWithVAT * item.quantity)
                    : '—'
                  }
                </TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Card>
  );
}

function CostSummaryCard({ items }: { items: RequestItem[] }) {
  const { t } = useTranslation();
  const pricedItems = items.filter((i) => i.finalPrice != null);
  const totalFCA = pricedItems.reduce((s, i) => {
    const base = i.inSellerStock ? (i.partnerPriceFCA ?? 0) : (i.rfqPrice ?? 0);
    return s + base * i.quantity;
  }, 0);
  const totalLogistics = pricedItems.reduce((s, i) => s + (i.logisticsCost ?? 0) * i.quantity, 0);
  const totalCustoms = pricedItems.reduce((s, i) => s + (i.customsDuty ?? 0) * i.quantity, 0);
  const totalLanded = pricedItems.reduce((s, i) => s + (i.landedCost ?? 0) * i.quantity, 0);
  const totalNoVAT = pricedItems.reduce((s, i) => s + (i.finalPrice ?? 0) * i.quantity, 0);
  const totalVAT = pricedItems.reduce((s, i) => s + (i.finalPriceWithVAT ?? 0) * i.quantity, 0);
  const marginAmt = totalNoVAT - totalLanded;
  const vatAmt = totalVAT - totalNoVAT;

  const waterfallData = [
    { name: t('requestDetail.cost.fca'), value: totalFCA, fill: 'var(--color-chart-1)' },
    { name: t('requestDetail.cost.logistics'), value: totalLogistics, fill: 'var(--color-chart-2)' },
    { name: t('requestDetail.cost.customs'), value: totalCustoms, fill: 'var(--color-chart-4)' },
    { name: t('requestDetail.cost.margin'), value: marginAmt, fill: 'var(--color-chart-3)' },
    { name: t('requestDetail.cost.vat'), value: vatAmt, fill: 'var(--color-chart-5)' },
    { name: t('requestDetail.cost.total'), value: totalVAT, fill: 'var(--color-chart-1)' },
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <Calculator className="h-4 w-4" /> {t('requestDetail.cost.title')}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          {/* Left: breakdown table */}
          <div className="space-y-2">
            <div className="grid grid-cols-2 gap-x-8 gap-y-2">
              <span className="text-sm text-muted-foreground">{t('requestDetail.cost.purchaseFCA')}</span>
              <span className="text-sm font-medium tabular-nums text-right">{formatCurrency(totalFCA)}</span>

              <span className="text-sm text-muted-foreground">{t('requestDetail.cost.logisticsDAP')}</span>
              <span className="text-sm tabular-nums text-right">{formatCurrency(totalLogistics)}</span>

              <span className="text-sm text-muted-foreground">{t('requestDetail.cost.customsDuty')}</span>
              <span className="text-sm tabular-nums text-right">{formatCurrency(totalCustoms)}</span>

              <Separator className="col-span-2 my-1" />

              <span className="text-sm font-medium">{t('requestDetail.cost.landedCostLabel')}</span>
              <span className="text-sm font-bold tabular-nums text-right">{formatCurrency(totalLanded)}</span>

              <span className="text-sm text-muted-foreground">{t('requestDetail.cost.marginWithPercent', { percent: pricedItems[0]?.marginPercent ?? 0 })}</span>
              <span className="text-sm tabular-nums text-right text-primary">{formatCurrency(marginAmt)}</span>

              <Separator className="col-span-2 my-1" />

              <span className="text-sm font-medium">{t('requestDetail.cost.subtotalExclVAT')}</span>
              <span className="text-sm font-bold tabular-nums text-right">{formatCurrency(totalNoVAT)}</span>

              <span className="text-sm text-muted-foreground">{t('requestDetail.cost.vat')}</span>
              <span className="text-sm tabular-nums text-right">{formatCurrency(vatAmt)}</span>

              <Separator className="col-span-2 my-1" />

              <span className="text-base font-bold">{t('requestDetail.cost.totalInclVAT')}</span>
              <span className="text-base font-bold tabular-nums text-right text-primary">{formatCurrency(totalVAT)}</span>
            </div>
          </div>

          {/* Right: waterfall chart */}
          <div>
            <p className="text-xs font-medium text-muted-foreground mb-3">{t('requestDetail.cost.structure')}</p>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={waterfallData}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--color-border)" />
                <XAxis dataKey="name" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
                <YAxis tick={{ fontSize: 11 }} tickLine={false} axisLine={false} tickFormatter={(v: number) => formatCurrency(v)} />
                <RechartsTooltip
                  formatter={(value: number) => [formatCurrency(value), t('requestDetail.cost.amount')]}
                  contentStyle={{ borderRadius: '8px', fontSize: '12px', border: '1px solid var(--color-border)' }}
                />
                <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                  {waterfallData.map((entry, i) => (
                    <Cell key={i} fill={entry.fill} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

/* ═══════════════════════════════════════════════════════════════════════
   MANUFACTURER VIEW — Factory fills in prices
   ═══════════════════════════════════════════════════════════════════════ */

function ManufacturerView({ onBack }: { onBack: () => void }) {
  const { t } = useTranslation();
  const { request, manufacturerRespond, resetFlow } = useFlowStore();

  // Manufacturer sees only items assigned to them
  const myItems = request.items.filter(
    (i) => (i.manufacturerId === 'SAUT' || i.manufacturerId === 'RATEP') && i.rfqStatus !== 'not_sent'
  );

  const respondedCount = myItems.filter((i) => i.rfqStatus === 'responded').length;
  const progress = myItems.length > 0 ? (respondedCount / myItems.length) * 100 : 0;

  if (myItems.length === 0) {
    return (
      <div className="flex flex-col gap-6">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" onClick={onBack}><ArrowLeft className="h-4 w-4" /></Button>
          <h1 className="text-2xl font-bold">{t('requestDetail.manufacturer.incomingRequests')}</h1>
        </div>
        <Card className="py-16">
          <CardContent className="flex flex-col items-center gap-3 text-muted-foreground">
            <Factory className="h-10 w-10" />
            <p className="text-sm font-medium">{t('requestDetail.manufacturer.noRequests')}</p>
            <p className="text-xs">{t('requestDetail.manufacturer.noRequestsHint')}</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="icon" onClick={onBack}><ArrowLeft className="h-4 w-4" /></Button>
        <div className="flex-1">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold">{t('requestDetail.manufacturer.rfqFrom', { seller: request.sellerName })}</h1>
            <Badge variant="outline" className="text-xs bg-primary/10 text-primary border-primary/20">
              {t('requestDetail.manufacturer.itemsCount', { count: myItems.length })}
            </Badge>
          </div>
          <p className="text-sm text-muted-foreground mt-0.5">
            {t('requestDetail.manufacturer.priceAndTerms', { number: request.number })}
          </p>
        </div>
        <Button variant="outline" size="sm" className="gap-2" onClick={resetFlow}>
          <RotateCcw className="h-3.5 w-3.5" /> {t('requestDetail.reset')}
        </Button>
      </div>

      {/* Progress */}
      <Card className="py-4 gap-2">
        <CardContent className="px-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium">{t('requestDetail.manufacturer.filled', { responded: respondedCount, total: myItems.length })}</span>
            <span className="text-sm text-muted-foreground">{Math.round(progress)}%</span>
          </div>
          <Progress value={progress} />
        </CardContent>
      </Card>

      {/* Items to fill */}
      <div className="space-y-3">
        {myItems.map((item) => (
          <ManufacturerItemCard key={item.id} item={item} onRespond={manufacturerRespond} />
        ))}
      </div>
    </div>
  );
}

function ManufacturerItemCard({
  item,
  onRespond,
}: {
  item: RequestItem;
  onRespond: (id: string, price: number, leadDays: number, note?: string) => void;
}) {
  const { t } = useTranslation();
  const [price, setPrice] = useState(item.rfqPrice?.toString() ?? '');
  const [leadDays, setLeadDays] = useState(item.rfqLeadDays?.toString() ?? '');
  const [note, setNote] = useState(item.rfqNote ?? '');
  const responded = item.rfqStatus === 'responded';

  const handleSubmit = () => {
    if (price && leadDays) {
      onRespond(item.id, Number(price), Number(leadDays), note || undefined);
    }
  };

  return (
    <Card className={cn('py-4 gap-2', responded && 'border-primary/20 bg-primary/5')}>
      <CardContent className="px-4">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:gap-6">
          {/* Item info */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <p className="font-medium">{item.name}</p>
              {responded && <CheckCircle2 className="h-4 w-4 text-primary" />}
            </div>
            <div className="flex items-center gap-3 mt-1 text-xs text-muted-foreground">
              <span>{t('requestDetail.manufacturer.article')}: {item.article}</span>
              <span>{t('requestDetail.manufacturer.gost')}: {item.gost}</span>
              <span>{t('requestDetail.manufacturer.qty')}: <strong className="text-foreground">{item.quantity} {item.uom}</strong></span>
            </div>
          </div>

          {/* Price + Lead time inputs */}
          <div className="flex items-end gap-3">
            <div className="space-y-1">
              <Label className="text-xs">{t('requestDetail.manufacturer.priceFCA')}</Label>
              <Input
                className="w-28 h-9"
                type="number"
                placeholder="0"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                disabled={responded}
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">{t('requestDetail.manufacturer.leadTimeDays')}</Label>
              <Input
                className="w-20 h-9"
                type="number"
                placeholder="0"
                value={leadDays}
                onChange={(e) => setLeadDays(e.target.value)}
                disabled={responded}
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">{t('requestDetail.manufacturer.note')}</Label>
              <Input
                className="w-40 h-9"
                placeholder={t('requestDetail.manufacturer.commentPlaceholder')}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                disabled={responded}
              />
            </div>
            {!responded ? (
              <Button size="sm" className="gap-1.5" disabled={!price || !leadDays} onClick={handleSubmit}>
                <Check className="h-3.5 w-3.5" /> {t('requestDetail.manufacturer.confirm')}
              </Button>
            ) : (
              <Badge className="bg-primary/10 text-primary h-9 px-3">{t('requestDetail.manufacturer.sent')}</Badge>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
