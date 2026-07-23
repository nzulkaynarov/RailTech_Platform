import { useTranslation } from 'react-i18next';
import type { CSSProperties } from 'react';
import type { DocumentBrandPreview } from '@/api/documentsApi';

interface DocumentLetterheadPreviewProps {
  /** The branded header/footer slice (backend `brand`). */
  brand: DocumentBrandPreview;
  /** The sanitised body HTML (server-side allowlist — safe to inject). */
  bodyHtml: string;
  /** Optional heading above the preview (e.g. «Предпросмотр документа»). */
  className?: string;
}

/**
 * The FULL branded document as the real PDF prints it: letterhead шапка (лого + название + ИНН +
 * контакты) → body → колонтитул. This is the whole point of «Документы 2.0» wave T1 — showing only
 * the bare body hid the letterhead and pushed authors to re-type the company requisites into the
 * body (a double print). Rendering the header here makes it obvious the requisites are already there.
 *
 * The brand accent is a per-company colour (not a semantic token), so it rides a `--doc-accent` CSS
 * custom property and every accent surface reads it via `var()` — the sanctioned escape hatch for
 * dynamic colours (no inline `backgroundColor`).
 *
 * D3 unified A4: the preview renders as an A4-proportioned white sheet (210/297; content may
 * stretch it taller) so EVERY document preview on the platform reads as the same physical page.
 * bg-white + text-neutral-900 are intentional (justified Rule 4 exception, same as the brand-settings
 * iframe): the sheet depicts PAPER, which stays white with dark ink in both UI themes.
 */
export function DocumentLetterheadPreview({ brand, bodyHtml, className }: DocumentLetterheadPreviewProps) {
  const { t } = useTranslation();
  const accentVars = { '--doc-accent': brand.accent, aspectRatio: '210/297' } as CSSProperties;
  const meta = [
    brand.inn ? t('docLetterhead.inn', { value: brand.inn }) : null,
    brand.phone ? t('docLetterhead.phone', { value: brand.phone }) : null,
    brand.email || null,
  ].filter(Boolean).join(' · ');

  return (
    <div
      style={accentVars}
      // eslint-disable-next-line railtech/no-hardcoded-colors -- A4 paper: white with dark ink in BOTH themes (justified Rule 4 exception, same as the brand-settings iframe)
      className={`mx-auto flex w-full max-w-[794px] flex-col overflow-hidden rounded-sm border border-border bg-white text-neutral-900 shadow-sm ${className ?? ''}`}
    >
      {/* Letterhead шапка */}
      <div className="px-6 pt-6">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            {brand.logo_url && (
              <img
                src={brand.logo_url}
                alt={brand.seller_name}
                className="max-h-12 max-w-[7.5rem] object-contain"
              />
            )}
            <div>
              <div className="text-lg font-bold text-[color:var(--doc-accent)]">{brand.seller_name}</div>
              {/* Paper neutrals (not theme tokens): the sheet is white in both UI themes. */}
              {/* eslint-disable-next-line railtech/no-hardcoded-colors -- paper ink, not UI theme */}
              {meta && <div className="mt-0.5 text-xs text-neutral-500">{meta}</div>}
            </div>
          </div>
        </div>
        {/* eslint-disable-next-line railtech/no-hardcoded-colors -- paper ink, not UI theme */}
        {brand.address && <div className="mt-1 text-xs text-neutral-500">{brand.address}</div>}
        <div className="mt-3 h-0.5 w-full bg-[color:var(--doc-accent)]" />
      </div>

      {/* Body — sanitised server-side (allowlist), safe to inject. */}
      <div
        className="prose prose-sm max-w-none px-6 py-5 text-sm [&_h3]:text-[color:var(--doc-accent)]"
        dangerouslySetInnerHTML={{ __html: bodyHtml }}
      />

      {/* Колонтитул — прижат к низу А4-листа */}
      {/* eslint-disable-next-line railtech/no-hardcoded-colors -- paper ink, not UI theme */}
      <div className="mt-auto border-t border-neutral-200 px-6 py-3 text-center text-xs text-neutral-500">
        {brand.footer_text}
      </div>
    </div>
  );
}

export default DocumentLetterheadPreview;
