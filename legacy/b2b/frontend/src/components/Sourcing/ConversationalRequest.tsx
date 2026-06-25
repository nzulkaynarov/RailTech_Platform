import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Sparkles, ChevronDown, Wand2, Plus, Check } from 'lucide-react';
import { toast } from 'sonner';
import { useComposeRequest, useAddRequestItem } from '@/hooks/useCRM';
import type { ComposedItem } from '@/api/aiApi';
import { translateApiError } from '@/lib/apiError';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';

/**
 * AI #8 — conversational заявка builder. The buyer describes a need in free text
 * ("нужны тормозные колодки на вагон, 4 комплекта, и подшипники буксовые") and
 * Claude proposes structured request line items grounded in the REAL catalog.
 *
 * Human-in-loop: NOTHING is auto-submitted. The buyer reviews each proposed line,
 * then accepts it (which adds it to the request grid via the normal add path) or
 * accepts all. The grid below remains the single source of truth.
 */
export function ConversationalRequest({ dealId }: { dealId: number }) {
  const { t } = useTranslation();
  const compose = useComposeRequest();
  const addItem = useAddRequestItem();

  const [open, setOpen] = useState(false);
  const [text, setText] = useState('');
  const [proposed, setProposed] = useState<ComposedItem[]>([]);
  const [accepted, setAccepted] = useState<Set<number>>(new Set());

  const handleCompose = async () => {
    const need = text.trim();
    if (!need) {
      toast.error(t('conversationalRequest.textRequired'));
      return;
    }
    try {
      const result = await compose.mutateAsync({ text: need });
      setProposed(result.items);
      setAccepted(new Set());
      if (result.items.length === 0) {
        toast.info(t('conversationalRequest.noItems'));
      }
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  // Fold the part code into the request line: mpn for an artikul, and keep any
  // ГОСТ/чертёж text in the note so it survives (the grid exposes one code field).
  const buildNote = (item: ComposedItem) => {
    const parts = [item.note?.trim(), item.gost_drawing?.trim() ? `ГОСТ/чертёж: ${item.gost_drawing.trim()}` : '']
      .filter(Boolean);
    return parts.join('. ');
  };

  const acceptOne = async (item: ComposedItem, index: number) => {
    if (accepted.has(index)) return;
    try {
      await addItem.mutateAsync({
        dealId,
        name: item.name,
        quantity: Math.max(1, item.quantity || 1),
        unit: item.unit || undefined,
        note: buildNote(item) || undefined,
        mpn: item.mpn || undefined,
      });
      setAccepted((prev) => new Set(prev).add(index));
      toast.success(t('conversationalRequest.accepted'));
    } catch (e) {
      toast.error(translateApiError(e));
    }
  };

  const acceptAll = async () => {
    for (let index = 0; index < proposed.length; index += 1) {
      if (!accepted.has(index)) {
        // Sequential so the backend stage/quote bootstrap stays consistent.
        // eslint-disable-next-line no-await-in-loop
        await acceptOne(proposed[index], index);
      }
    }
  };

  const allAccepted = proposed.length > 0 && proposed.every((_, index) => accepted.has(index));

  return (
    <Collapsible
      open={open}
      onOpenChange={setOpen}
      className="rounded-lg border border-border bg-muted/30"
    >
      <CollapsibleTrigger asChild>
        <button
          type="button"
          className="flex w-full items-center justify-between gap-2 px-4 py-3 text-left"
        >
          <span className="flex items-center gap-2 text-sm font-medium">
            <Sparkles className="h-4 w-4 text-primary" />
            {t('conversationalRequest.title')}
          </span>
          <ChevronDown
            className={`h-4 w-4 text-muted-foreground transition-transform ${open ? 'rotate-180' : ''}`}
          />
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent className="space-y-3 px-4 pb-4">
        <p className="text-xs text-muted-foreground">{t('conversationalRequest.hint')}</p>
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={t('conversationalRequest.placeholder')}
          rows={3}
          className="resize-y text-sm"
          aria-label={t('conversationalRequest.title')}
        />
        <Button onClick={handleCompose} disabled={compose.isPending} size="sm" className="gap-1.5">
          <Wand2 className="h-4 w-4" />
          {compose.isPending ? t('conversationalRequest.composing') : t('conversationalRequest.compose')}
        </Button>

        {proposed.length > 0 && (
          <div className="space-y-2 border-t border-border pt-3">
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-medium text-muted-foreground">
                {t('conversationalRequest.proposedTitle')}
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={acceptAll}
                disabled={allAccepted || addItem.isPending}
                className="h-7 gap-1.5"
              >
                <Plus className="h-3.5 w-3.5" />
                {t('conversationalRequest.acceptAll')}
              </Button>
            </div>
            <ul className="space-y-2">
              {proposed.map((item, index) => {
                const isAccepted = accepted.has(index);
                return (
                  <li
                    key={index}
                    className="flex items-start justify-between gap-3 rounded-md border border-border bg-background p-2.5"
                  >
                    <div className="min-w-0 space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium">{item.name || t('conversationalRequest.unnamed')}</span>
                        <Badge variant="secondary" className="font-normal tabular-nums">
                          {item.quantity} {item.unit}
                        </Badge>
                        {item.candidates.length > 0 && (
                          <Badge variant="outline" className="font-normal">
                            {t('conversationalRequest.candidatesCount', { count: item.candidates.length })}
                          </Badge>
                        )}
                      </div>
                      {item.mpn && (
                        <span className="block text-xs text-muted-foreground">
                          {t('conversationalRequest.codeLabel')}: <span className="font-mono">{item.mpn}</span>
                        </span>
                      )}
                      {item.note && <span className="block text-xs text-muted-foreground">{item.note}</span>}
                    </div>
                    <Button
                      variant={isAccepted ? 'ghost' : 'outline'}
                      size="sm"
                      onClick={() => acceptOne(item, index)}
                      disabled={isAccepted || addItem.isPending}
                      className="h-7 shrink-0 gap-1.5"
                    >
                      {isAccepted ? (
                        <>
                          <Check className="h-3.5 w-3.5 text-success" />
                          {t('conversationalRequest.added')}
                        </>
                      ) : (
                        <>
                          <Plus className="h-3.5 w-3.5" />
                          {t('conversationalRequest.accept')}
                        </>
                      )}
                    </Button>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </CollapsibleContent>
    </Collapsible>
  );
}
