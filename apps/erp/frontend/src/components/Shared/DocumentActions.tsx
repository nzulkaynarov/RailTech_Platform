import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Eye, Printer, FileText, FileSpreadsheet, FileType, Link2, Loader2, Share2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { translateApiError } from '@/lib/apiError';
import { extractBlobErrorCode, fetchDocumentBlob, printBlob, saveBlob } from '@/lib/documents';

export type DocFormat = 'pdf' | 'xlsx' | 'csv';

export interface DocumentActionsProps {
  /** Maps a format to the streaming endpoint that returns its bytes. */
  request: (format: DocFormat) => { path: string; params?: Record<string, string> };
  /** Base filename (no extension), e.g. `Contract_12`. */
  filenameBase: string;
  /** Downloadable formats (default ['pdf']). Non-PDF formats are download-only. */
  formats?: DocFormat[];
  /** Show «Просмотр» (opens the PDF inline). Default true. */
  enablePreview?: boolean;
  /** Show «Печать». Default true. */
  enablePrint?: boolean;
  /** Public share link to copy (e.g. the public КП link). Omit to hide «Копировать ссылку». */
  publicLink?: string;
  disabled?: boolean;
  label?: string;
  size?: 'sm' | 'default';
  variant?: 'default' | 'outline' | 'ghost';
  /** Render an icon-only trigger (for tight table rows). */
  iconOnly?: boolean;
}

const FORMAT_ICON: Record<DocFormat, React.ReactNode> = {
  pdf: <FileText className="size-4" />,
  xlsx: <FileSpreadsheet className="size-4" />,
  csv: <FileType className="size-4" />,
};

/**
 * Unified export / share control for every document (КП / договор / инвойс / акт).
 * One affordance for: Просмотр (inline preview) · Печать · Скачать PDF/Excel/CSV · Копировать
 * ссылку. All actions stream the bytes through the ARCH-03 202-aware fetch and surface the
 * specific server refusal code ({"detail": CODE}) instead of a generic error.
 */
export const DocumentActions: React.FC<DocumentActionsProps> = ({
  request,
  filenameBase,
  formats = ['pdf'],
  enablePreview = true,
  enablePrint = true,
  publicLink,
  disabled,
  label,
  size = 'sm',
  variant = 'outline',
  iconOnly = false,
}) => {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);

  const run = async (fn: (blob: Blob) => void, format: DocFormat) => {
    setBusy(true);
    try {
      const { path, params } = request(format);
      const blob = await fetchDocumentBlob(path, params);
      fn(blob);
    } catch (err) {
      const code = await extractBlobErrorCode(err);
      toast.error(code ? translateApiError(code) : t('errors.operationFailed'));
    } finally {
      setBusy(false);
    }
  };

  const onDownload = (format: DocFormat) =>
    run((blob) => saveBlob(blob, `${filenameBase}.${format}`), format);

  const onPreview = async () => {
    // window.open MUST run synchronously inside the click gesture — after an `await` the browser
    // has consumed the user-activation and the popup blocker kills it. So open a blank tab NOW,
    // then point it at the blob once the fetch lands. (No `noopener` — that makes open() return
    // null, hiding whether it was truly blocked.)
    const previewWindow = window.open('', '_blank');
    setBusy(true);
    try {
      const { path, params } = request('pdf');
      const blob = await fetchDocumentBlob(path, params);
      const url = window.URL.createObjectURL(blob);
      if (previewWindow) {
        previewWindow.location.href = url;
        window.setTimeout(() => window.URL.revokeObjectURL(url), 60_000);
      } else {
        // Popup blocked at open time → save the file so the user still gets it.
        saveBlob(blob, `${filenameBase}.pdf`);
        toast.error(t('docActions.popupBlocked'));
      }
    } catch (err) {
      previewWindow?.close();
      const code = await extractBlobErrorCode(err);
      toast.error(code ? translateApiError(code) : t('errors.operationFailed'));
    } finally {
      setBusy(false);
    }
  };

  const onPrint = () => run((blob) => printBlob(blob), 'pdf');

  const onCopyLink = async () => {
    if (!publicLink) return;
    try {
      await navigator.clipboard.writeText(publicLink);
      toast.success(t('docActions.linkCopied'));
    } catch {
      toast.error(t('errors.operationFailed'));
    }
  };

  const hasPdf = formats.includes('pdf');

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        {iconOnly ? (
          <Button size="icon" variant={variant} disabled={disabled || busy} aria-label={label ?? t('docActions.menu')}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : <Share2 className="size-4" />}
          </Button>
        ) : (
          <Button size={size} variant={variant} disabled={disabled || busy}>
            {busy ? <Loader2 className="size-3 animate-spin" /> : <Share2 className="size-3" />}
            {label ?? t('docActions.menu')}
          </Button>
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {hasPdf && enablePreview && (
          <DropdownMenuItem disabled={busy} onSelect={onPreview}>
            <Eye className="size-4" />
            {t('docActions.preview')}
          </DropdownMenuItem>
        )}
        {hasPdf && enablePrint && (
          <DropdownMenuItem disabled={busy} onSelect={onPrint}>
            <Printer className="size-4" />
            {t('docActions.print')}
          </DropdownMenuItem>
        )}
        {hasPdf && (enablePreview || enablePrint) && <DropdownMenuSeparator />}
        {formats.map((format) => (
          <DropdownMenuItem key={format} disabled={busy} onSelect={() => onDownload(format)}>
            {FORMAT_ICON[format]}
            {t(`docActions.download.${format}`)}
          </DropdownMenuItem>
        ))}
        {publicLink && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={onCopyLink}>
              <Link2 className="size-4" />
              {t('docActions.copyLink')}
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
};
