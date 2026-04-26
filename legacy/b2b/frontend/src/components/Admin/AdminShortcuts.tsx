import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

interface AdminShortcutsProps {
  /** Navigate to an admin page id (e.g. 'admin-kyc'). */
  onNavigate: (pageId: string) => void;
  /** Open the global Cmd+K palette. */
  onOpenPalette: () => void;
}

function isEditableElement(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  const tag = el.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (el.isContentEditable) return true;
  return false;
}

/**
 * Global keyboard shortcut layer for the Platform Admin SPA.
 *
 * Bindings (all ignored when focus is in an input / textarea / editable):
 *   ?         — open the shortcuts cheat sheet
 *   /         — focus the first search input on the page
 *   g k       — go to KYC (Cmd+K stays as the palette opener)
 *   g c       — go to Companies
 *   g u       — go to Users
 *   g d       — go to Deals
 *   g s       — go to Subscriptions
 *   g r       — go to Role Applications
 *   g h       — go to Dashboard (Home)
 */
export function AdminShortcuts({ onNavigate, onOpenPalette }: AdminShortcutsProps): React.ReactNode {
  const { t } = useTranslation();
  const [helpOpen, setHelpOpen] = useState(false);

  // Tracks the "g" prefix for two-key "go to" combos.
  const gModeRef = useRef<number | null>(null);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (isEditableElement(e.target)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      // Cmd+K shortcut is handled by useCommandPaletteShortcut. Plain "k"
      // is reserved here as potential row-nav, so ignore.
      if (e.key === '?') {
        e.preventDefault();
        setHelpOpen(true);
        return;
      }
      if (e.key === '/' ) {
        const target = document.querySelector<HTMLInputElement>(
          'input[type="search"]',
        ) ?? document.querySelector<HTMLInputElement>(
          'input[placeholder*="Поиск"], input[placeholder*="Search"]',
        );
        if (target) {
          e.preventDefault();
          target.focus();
        }
        return;
      }
      if (e.key === 'p' && !gModeRef.current) {
        // Shift+P / Ctrl+K exist for palette via other paths; keep plain P unassigned.
      }

      // "g" prefix mode — await next key for a "go to" combo.
      if (e.key === 'g' && !gModeRef.current) {
        gModeRef.current = window.setTimeout(() => {
          gModeRef.current = null;
        }, 1500);
        return;
      }

      if (gModeRef.current) {
        const map: Record<string, string> = {
          h: 'dashboard',
          k: 'admin-kyc',
          c: 'admin-companies',
          u: 'admin-users',
          d: 'admin-deals',
          s: 'admin-subscriptions',
          r: 'admin-role-apps',
          o: 'admin-offers',
          p: 'admin-catalog',
          t: 'admin-support',
        };
        const target = map[e.key.toLowerCase()];
        window.clearTimeout(gModeRef.current);
        gModeRef.current = null;
        if (target) {
          e.preventDefault();
          onNavigate(target);
        }
      }
    }

    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      if (gModeRef.current) {
        window.clearTimeout(gModeRef.current);
        gModeRef.current = null;
      }
    };
  }, [onNavigate, onOpenPalette]);

  const shortcuts: { keys: string[]; label: string }[] = [
    { keys: ['Cmd', 'K'], label: t('adminShortcuts.palette') },
    { keys: ['?'], label: t('adminShortcuts.help') },
    { keys: ['/'], label: t('adminShortcuts.focusSearch') },
    { keys: ['g', 'h'], label: t('adminShortcuts.goDashboard') },
    { keys: ['g', 'k'], label: t('adminShortcuts.goKyc') },
    { keys: ['g', 'c'], label: t('adminShortcuts.goCompanies') },
    { keys: ['g', 'u'], label: t('adminShortcuts.goUsers') },
    { keys: ['g', 'd'], label: t('adminShortcuts.goDeals') },
    { keys: ['g', 's'], label: t('adminShortcuts.goSubscriptions') },
    { keys: ['g', 'r'], label: t('adminShortcuts.goRoleApps') },
    { keys: ['g', 't'], label: t('adminShortcuts.goSupport') },
    { keys: ['j', '/', 'k'], label: t('adminShortcuts.tableNav') },
    { keys: ['Enter'], label: t('adminShortcuts.tableOpen') },
    { keys: ['x'], label: t('adminShortcuts.tableSelect') },
  ];

  return (
    <Dialog open={helpOpen} onOpenChange={setHelpOpen}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('adminShortcuts.title')}</DialogTitle>
          <DialogDescription>{t('adminShortcuts.description')}</DialogDescription>
        </DialogHeader>
        <ul className="mt-2 space-y-1 text-xs">
          {shortcuts.map((s) => (
            <li
              key={s.label}
              className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5 hover:bg-muted/60"
            >
              <span>{s.label}</span>
              <span className="flex items-center gap-1">
                {s.keys.map((k, idx) => (
                  <kbd
                    key={idx}
                    className="rounded border bg-muted px-1.5 py-0.5 font-mono text-xs"
                  >
                    {k}
                  </kbd>
                ))}
              </span>
            </li>
          ))}
        </ul>
      </DialogContent>
    </Dialog>
  );
}
