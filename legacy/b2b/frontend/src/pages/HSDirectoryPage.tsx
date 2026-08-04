import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { BookOpenText, ChevronRight, Copy, Landmark, Loader2, Sparkles } from 'lucide-react';
import { toast } from 'sonner';
import { CustomsDutiesSheet } from '@/components/Shared/CustomsDutiesSheet';

import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Skeleton } from '@/components/ui/skeleton';
import { useHSCodeSuggest } from '@/hooks/useCatalog';
import { useDebouncedValue } from '@/hooks/useDebouncedValue';
import { MIN_QUERY_LENGTH, formatHSCode, leafName } from '@/components/Shared/HSCodeField';
import { runAiJob } from '@/lib/aiJob';
import { apiClient } from '@/api/client';
import { extractApiErrorCode, translateApiError } from '@/lib/apiError';

/**
 * Страница «Справочник ТН ВЭД» (T3, spec-tnved-flow) — две модальности поиска.
 *
 * Эталон — WCO Trade Tools и сам tarif.customs.uz: дерево 2→4→6→10 с текстовым поиском для
 * случаев «не знаю, как это зовётся у таможни». Плюс ИИ-режим (Avalara/Zonos): свободное
 * описание → код из классификатора с объяснением одной фразой. ИИ выбирает ТОЛЬКО из
 * кандидатов справочника, выбор сверяется на сервере — придуманный код невозможен по
 * построению.
 *
 * Классификатор read-only: править его нельзя никому — он приходит из ГТК автосинком.
 */

interface HSNode {
  code: string;
  name: string;
  level: number;
  has_children: boolean;
}

interface LookupResult {
  code: string;
  name: string;
  explanation: string;
  candidates: { code: string; name: string }[];
}

/** N4: кнопка ИИ-режима не активна до этой длины — и интерфейс говорит об этом словами. */
const AI_MIN_DESCRIPTION = 5;

function copyCode(code: string, done: (message: string) => void) {
  navigator.clipboard?.writeText(code).then(() => done(code));
}

/** Одна ветка дерева: раскрытие подгружает детей лениво (иначе 13 тыс. узлов разом). */
function TreeNode({ node, depth }: { node: HSNode; depth: number }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [children, setChildren] = useState<HSNode[] | null>(null);
  const [loading, setLoading] = useState(false);
  // Панель платежей открывается по конкретному коду — монтируем её только на время показа.
  const [dutiesCode, setDutiesCode] = useState('');

  const toggle = async () => {
    if (!node.has_children) return;
    setOpen((was) => !was);
    if (children === null && !loading) {
      setLoading(true);
      try {
        const response = await apiClient.get<{ children: HSNode[] }>('catalog/products/hs-browse/', {
          params: { parent: node.code },
        });
        setChildren(response.data.children);
      } catch {
        // N2 (M5): без catch отказ сети оставлял ветку молча пустой; null позволяет
        // повторить раскрытие, а пользователь видит тост вместо тишины.
        setChildren(null);
        setOpen(false);
        toast.error(t('hsDirectory.treeFailed'));
      } finally {
        setLoading(false);
      }
    }
  };

  return (
    <div>
      <div
        className={cn('flex items-start gap-2 rounded-md px-2 py-1.5 hover:bg-muted/60', node.has_children && 'cursor-pointer')}
        style={{ paddingLeft: `${depth * 1.25 + 0.5}rem` }}
        onClick={toggle}
      >
        {node.has_children ? (
          <ChevronRight className={cn('mt-0.5 h-4 w-4 shrink-0 transition-transform', open && 'rotate-90')} aria-hidden="true" />
        ) : (
          <span className="w-4 shrink-0" />
        )}
        <span className="font-mono text-xs font-semibold tabular-nums">{formatHSCode(node.code)}</span>
        <span className="min-w-0 flex-1 text-sm">{leafName(node.name)}</span>
        {node.code.length === 10 && (
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6 shrink-0"
            aria-label={t('customsDuties.action')}
            title={t('customsDuties.action')}
            onClick={(event) => {
              event.stopPropagation();
              setDutiesCode(node.code);
            }}
          >
            <Landmark className="h-3.5 w-3.5" aria-hidden="true" />
          </Button>
        )}
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6 shrink-0"
          aria-label={t('hsDirectory.copy', { code: node.code })}
          onClick={(event) => {
            event.stopPropagation();
            copyCode(node.code, (code) => toast.success(t('hsDirectory.copied', { code })));
          }}
        >
          <Copy className="h-3.5 w-3.5" aria-hidden="true" />
        </Button>
      </div>
      {dutiesCode && (
        <CustomsDutiesSheet
          hsCode={dutiesCode}
          hsName={leafName(node.name)}
          open
          onOpenChange={(next) => !next && setDutiesCode('')}
        />
      )}
      {open && loading && <Skeleton className="ml-10 h-6 w-64" />}
      {open && children?.map((child) => <TreeNode key={child.code} node={child} depth={depth + 1} />)}
    </div>
  );
}

export function HSDirectoryPage() {
  const { t } = useTranslation();
  const [query, setQuery] = useState('');
  const debounced = useDebouncedValue(query, 300);
  const { data: found } = useHSCodeSuggest(debounced.length >= MIN_QUERY_LENGTH ? debounced : '');

  // N2 (M5): раньше корни грузились прямо в теле рендера без .catch — любая ошибка сети
  // давала БЕСКОНЕЧНЫЙ цикл запросов и вечно пустое дерево без ретрая. useQuery даёт
  // состояние ошибки и кнопку «повторить».
  const {
    data: rootsData,
    isLoading: rootsLoading,
    isError: rootsError,
    refetch: refetchRoots,
  } = useQuery({
    queryKey: ['hs-browse-roots'],
    queryFn: async () =>
      (await apiClient.get<{ children: HSNode[] }>('catalog/products/hs-browse/')).data.children,
    staleTime: 10 * 60_000,
  });
  const roots = rootsData ?? null;

  const [description, setDescription] = useState('');
  const [aiBusy, setAiBusy] = useState(false);
  const [aiResult, setAiResult] = useState<LookupResult | null>(null);

  const askAi = async () => {
    setAiBusy(true);
    setAiResult(null);
    try {
      const result = await runAiJob<LookupResult>(async () => {
        const response = await apiClient.post<{ task_id: string }>('catalog/products/hs-lookup/', { description });
        return response.data;
      });
      setAiResult(result);
    } catch (err) {
      // Честный тост (N2, M3): 429/403 несут код — показываем его, а не безликое «не удалось».
      toast.error(extractApiErrorCode(err) ? translateApiError(err) : t('hsDirectory.ai.failed'));
    } finally {
      setAiBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-muted">
          <BookOpenText className="h-5 w-5" aria-hidden="true" />
        </div>
        <div>
          <h1 className="text-2xl font-bold">{t('hsDirectory.title')}</h1>
          <p className="text-sm text-muted-foreground">{t('hsDirectory.subtitle')}</p>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Обычный поиск + дерево */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">{t('hsDirectory.search.title')}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t('hsDirectory.search.placeholder')}
            />
            {found && found.length > 0 && (
              <div className="flex flex-col gap-1 rounded-md border p-2">
                {found.map((row) => (
                  <div key={row.code} className="flex items-start gap-2 rounded px-1.5 py-1 hover:bg-muted/60">
                    <span className="font-mono text-xs font-semibold">{formatHSCode(row.code)}</span>
                    <span className="min-w-0 flex-1 text-sm">{leafName(row.name)}</span>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6 shrink-0"
                      aria-label={t('hsDirectory.copy', { code: row.code })}
                      onClick={() => copyCode(row.code, (code) => toast.success(t('hsDirectory.copied', { code })))}
                    >
                      <Copy className="h-3.5 w-3.5" aria-hidden="true" />
                    </Button>
                  </div>
                ))}
              </div>
            )}
            <div className="max-h-112 overflow-y-auto rounded-md border p-1">
              {rootsLoading && <Skeleton className="m-2 h-6 w-64" />}
              {rootsError && (
                <div className="flex flex-col items-start gap-2 p-4">
                  <p className="text-sm text-muted-foreground">{t('hsDirectory.treeFailed')}</p>
                  <Button variant="outline" size="sm" onClick={() => refetchRoots()}>
                    {t('hsDirectory.retry')}
                  </Button>
                </div>
              )}
              {roots?.map((node) => <TreeNode key={node.code} node={node} depth={0} />)}
              {roots !== null && roots.length === 0 && (
                <p className="p-4 text-sm text-muted-foreground">{t('hsDirectory.empty')}</p>
              )}
            </div>
          </CardContent>
        </Card>

        {/* ИИ-режим: свободное описание */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Sparkles className="h-4 w-4" aria-hidden="true" />
              {t('hsDirectory.ai.title')}
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <p className="text-xs text-muted-foreground">{t('hsDirectory.ai.hint')}</p>
            <Textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder={t('hsDirectory.ai.placeholder')}
              rows={3}
            />
            {description.trim().length > 0 && description.trim().length < AI_MIN_DESCRIPTION && (
              <p className="text-xs text-muted-foreground">{t('hsDirectory.ai.minLength', { count: AI_MIN_DESCRIPTION })}</p>
            )}
            <Button onClick={askAi} disabled={aiBusy || description.trim().length < AI_MIN_DESCRIPTION} className="self-start">
              {aiBusy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" /> : null}
              {t('hsDirectory.ai.ask')}
            </Button>
            {aiResult && (
              <div className="flex flex-col gap-2 rounded-md border p-3">
                {aiResult.code ? (
                  <>
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-sm font-bold">{formatHSCode(aiResult.code)}</span>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => copyCode(aiResult.code, (code) => toast.success(t('hsDirectory.copied', { code })))}
                      >
                        <Copy className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
                        {t('hsDirectory.ai.copy')}
                      </Button>
                    </div>
                    <p className="text-sm">{leafName(aiResult.name)}</p>
                    <p className="text-xs text-muted-foreground">{aiResult.explanation}</p>
                  </>
                ) : (
                  <>
                    <p className="text-sm">{t('hsDirectory.ai.nothing')}</p>
                    {aiResult.explanation && <p className="text-xs text-muted-foreground">{aiResult.explanation}</p>}
                    {aiResult.candidates.length > 0 && (
                      <div className="flex flex-col gap-1">
                        {aiResult.candidates.slice(0, 5).map((row) => (
                          <div key={row.code} className="flex items-start gap-2 text-xs">
                            <span className="font-mono font-semibold">{formatHSCode(row.code)}</span>
                            <span className="text-muted-foreground">{leafName(row.name)}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export default HSDirectoryPage;
