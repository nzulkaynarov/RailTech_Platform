import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useBlocker } from 'react-router-dom';
import { Loader2, RotateCcw, Save } from 'lucide-react';

import { ActionDialog } from '@/components/ActionDialog';
import { Button } from '@/components/ui/button';
import { shortcutLabel } from '@/lib/keyboard';
import { cn } from '@/lib/utils';

export interface UnsavedChangesBarProps {
  /** Есть несохранённые изменения — бар виден (место под него зарезервировано всегда). */
  dirty: boolean;
  onSave: () => void;
  onReset: () => void;
  /** Идёт сохранение: кнопки заблокированы, вопроса при уходе нет. */
  pending?: boolean;
  className?: string;
}

/** Зазор между полем в фокусе и верхом бара. */
const FIELD_GAP = 16;

/** Ближайший прокручиваемый предок; без него прокручивается само окно. */
function scrollParent(node: HTMLElement): HTMLElement | null {
  for (let el = node.parentElement; el; el = el.parentElement) {
    const overflow = getComputedStyle(el).overflowY;
    if ((overflow === 'auto' || overflow === 'scroll') && el.scrollHeight > el.clientHeight) return el;
  }
  return null;
}

/**
 * Бар несохранённых изменений формы (CAB-FIX-3, K9; образец — `ContextualSaveBar` Платформы): последний элемент формы,
 * подвал на всю её ширину, прилипает к низу окна (на телефоне — над нижней навигацией). Место под бар зарезервировано и
 * без правок — бар невидим, но держит высоту: форма не прыгает ни при первом символе, ни при сохранении или сбросе.
 *
 * - Кнопка сохранения одна — в баре; «Сбросить» спрашивает подтверждение.
 * - Ctrl+S / ⌘S (и в раскладке RU, по `event.code`) сохраняет, только пока есть правки; без правок сочетание — браузеру.
 * - Уход со страницы по ссылке меню, крошке или «Назад» спрашивает «Выйти без сохранения?» (`useBlocker`),
 *   закрытие вкладки — предупреждение браузера (`beforeunload`).
 * - Поле в фокусе никогда не уходит под бар: у полей формы `scroll-margin-bottom`, а если поле всё же под баром
 *   (фокус, ввод, рост поля) — страница прокручивается ровно настолько, чтобы поле стояло над баром.
 *
 * Только для обратимого сохранения (DECISIONS 2026-10-30 п. 5): отправка заявки остаётся главной кнопкой формы.
 */
export function UnsavedChangesBar({ dirty, onSave, onReset, pending = false, className }: UnsavedChangesBarProps) {
  const { t } = useTranslation();
  const dockRef = useRef<HTMLDivElement>(null);
  const barRef = useRef<HTMLDivElement>(null);
  const [confirmReset, setConfirmReset] = useState(false);

  useEffect(() => {
    if (!dirty) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.altKey || event.shiftKey) return;
      if (event.code !== 'KeyS' && event.key.toLowerCase() !== 's') return;
      event.preventDefault();
      if (!pending) onSave();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [dirty, pending, onSave]);

  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, [dirty]);

  // Поле в фокусе — над баром: после фокуса, ввода и появления бара.
  useEffect(() => {
    const scope = dockRef.current?.parentElement;
    const bar = barRef.current;
    if (!scope || !bar || !dirty) return;
    let frame = 0;
    const reveal = (target: EventTarget | Element | null) => {
      if (!(target instanceof HTMLElement) || bar.contains(target) || !scope.contains(target)) return;
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        const barBox = bar.getBoundingClientRect();
        if (barBox.height === 0) return; // нет раскладки (скрыт, jsdom)
        const overlap = target.getBoundingClientRect().bottom + FIELD_GAP - barBox.top;
        if (overlap <= 0) return;
        const parent = scrollParent(bar);
        if (parent) parent.scrollBy({ top: overlap });
        else window.scrollBy({ top: overlap });
      });
    };
    const onEvent = (event: Event) => reveal(event.target);
    scope.addEventListener('focusin', onEvent);
    scope.addEventListener('input', onEvent);
    reveal(document.activeElement);
    return () => {
      window.cancelAnimationFrame(frame);
      scope.removeEventListener('focusin', onEvent);
      scope.removeEventListener('input', onEvent);
    };
  }, [dirty]);

  const message = t('saveBar.message');

  return (
    <div
      ref={dockRef}
      data-save-dock=""
      className={cn('sticky bottom-[calc(4rem+env(safe-area-inset-bottom))] z-20 mt-2 md:bottom-3', className)}
    >
      <span role="status" className="sr-only">
        {dirty ? message : ''}
      </span>
      <UnsavedGuard when={dirty && !pending} />
      <div
        ref={barRef}
        role="region"
        aria-label={t('saveBar.label')}
        aria-hidden={dirty ? undefined : true}
        // Без правок бар невидим, но держит место: форма не прыгает на первом символе.
        {...(dirty ? {} : { inert: '' })}
        className={cn(
          'flex w-full flex-wrap items-center justify-between gap-x-3 gap-y-2 rounded-xl border bg-card px-4 py-2 text-card-foreground shadow-lg',
          !dirty && 'invisible',
        )}
      >
        <div className="flex min-w-0 items-center gap-2.5 text-sm font-medium" aria-hidden="true">
          <span className="size-2 shrink-0 rounded-full bg-warning" />
          <span className="truncate">{message}</span>
          <kbd
            data-testid="save-shortcut"
            className="hidden rounded border px-1.5 font-sans text-xs text-muted-foreground sm:pointer-fine:inline"
          >
            {shortcutLabel('S')}
          </kbd>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <Button type="button" variant="outline" size="sm" onClick={() => setConfirmReset(true)} disabled={pending}>
            <RotateCcw aria-hidden="true" />
            {t('saveBar.reset')}
          </Button>
          <Button type="button" size="sm" onClick={onSave} disabled={pending}>
            {pending ? <Loader2 className="motion-safe:animate-spin" aria-hidden="true" /> : <Save aria-hidden="true" />}
            {t('saveBar.save')}
          </Button>
        </div>
      </div>
      <ActionDialog
        open={confirmReset}
        onOpenChange={setConfirmReset}
        title={t('saveBar.resetTitle')}
        description={t('saveBar.resetText')}
        confirmLabel={t('saveBar.resetConfirm')}
        confirmVariant="destructive"
        cancelLabel={t('saveBar.keepEditing')}
        pending={false}
        onSubmit={() => {
          setConfirmReset(false);
          onReset();
        }}
      />
    </div>
  );
}

/**
 * Вопрос «Выйти без сохранения?» при уходе со страницы с несохранёнными правками: ссылка меню, крошка, «Назад»
 * браузера или Telegram (`useBlocker` роутера данных). Смена только `?…` или `#…` той же страницы вопроса не вызывает.
 */
export function UnsavedGuard({ when }: { when: boolean }) {
  const { t } = useTranslation();
  const blocker = useBlocker(({ currentLocation, nextLocation }) => when && currentLocation.pathname !== nextLocation.pathname);
  return (
    <ActionDialog
      open={blocker.state === 'blocked'}
      onOpenChange={(open) => {
        if (!open && blocker.state === 'blocked') blocker.reset();
      }}
      title={t('unsavedGuard.title')}
      description={t('unsavedGuard.text')}
      confirmLabel={t('unsavedGuard.leave')}
      confirmVariant="destructive"
      cancelLabel={t('unsavedGuard.stay')}
      pending={false}
      onSubmit={() => {
        if (blocker.state === 'blocked') blocker.proceed();
      }}
    />
  );
}
