import { useTranslation } from 'react-i18next';

interface DocumentHtmlPreviewProps {
  /** Full branded document HTML rendered by the SERVER using the real PDF template
   *  (crm/generated_document_pdf.html → _document_base.html). This is the 1:1 preview:
   *  the same markup WeasyPrint rasterises, so it cannot drift from the exported PDF. */
  html: string;
  /** Accessible iframe title (also the label a screen reader announces). */
  title?: string;
  className?: string;
}

/**
 * Renders a document preview from server-authored HTML in a sandboxed iframe — the 1:1 replacement
 * for the old hand-written React letterhead (which re-implemented the шапка/тема and drifted from the
 * PDF: it ignored layout preset, font, secondary tint, bank block, signatory). The server sends the
 * ACTUAL document template, so what the author sees here is what prints.
 *
 * `allow-same-origin` lets Chrome PAINT the srcDoc (an opaque-origin sandbox renders blank); scripts
 * stay blocked (no `allow-scripts`) so any markup a seller puts in their requisites can't execute.
 * bg-white is a justified Rule 4 exception (same as the brand-settings iframe): the iframe depicts
 * A4 PAPER, which is white with dark ink in BOTH UI themes.
 */
export function DocumentHtmlPreview({ html, title, className }: DocumentHtmlPreviewProps) {
  const { t } = useTranslation();
  return (
    <iframe
      title={title ?? t('docLetterhead.previewTitle')}
      srcDoc={html}
      sandbox="allow-same-origin"
      // eslint-disable-next-line railtech/no-hardcoded-colors -- A4 paper: white in BOTH themes (justified Rule 4 exception, same as the brand-settings iframe)
      className={`w-full rounded-lg border border-border bg-white ${className ?? 'h-[70vh]'}`}
    />
  );
}

export default DocumentHtmlPreview;
