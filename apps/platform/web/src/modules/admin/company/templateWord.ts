import { downloadFile } from "../../../shared/api/download";
import {
  getDownloadDocumentSampleUrl,
  getDocumentSample,
  requestDocumentSample,
} from "../../../shared/api/generated/platform-bff";

export type DocumentTemplateLanguage = "ru" | "uz" | "en";

export const WORD_LANGUAGES: DocumentTemplateLanguage[] = ["ru", "uz", "en"];

/**
 * Имя скачанного файла — одно правило для Word и PDF: «<Название>, ред. <N> — проект.docx». Язык, кроме русского, —
 * в названии: «Договор (UZ), ред. 2 — проект.docx». Те же правила у сервера (`template_word.download_name`).
 */
export function templateFileName(
  name: string,
  edition: number,
  language: DocumentTemplateLanguage,
  extension: "docx" | "pdf",
): string {
  const printable = Array.from(name)
    .filter((char) => char.charCodeAt(0) >= 32)
    .join("");
  const clean = printable
    .replace(/[\\/:*?"<>|]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 120)
    .trim();
  const base = clean || "Шаблон";
  const titled = language === "ru" ? base : `${base} (${language.toUpperCase()})`;
  return titled + ", ред. " + String(edition) + " — проект." + extension;
}

const POLL_MS = 1000;
const MAX_WAIT_MS = 90_000;

/** PDF сохранённого шаблона на тестовых данных: тот же образец, что справа в редакторе (очередь ERP, опрос до готовности). */
export async function downloadTemplatePdf(
  template: { id: string; name: string; edition: number },
  language: DocumentTemplateLanguage,
): Promise<void> {
  const queued = await requestDocumentSample({ template_id: Number(template.id), language });
  const started = Date.now();
  for (;;) {
    const state = await getDocumentSample(queued.id);
    if (state.status === "ready") break;
    if (state.status === "failed") throw new Error(state.failure_code ?? "SAMPLE_RENDER_FAILED");
    if (Date.now() - started > MAX_WAIT_MS) throw new Error("SAMPLE_TIMEOUT");
    await new Promise((resolve) => window.setTimeout(resolve, POLL_MS));
  }
  await downloadFile(
    getDownloadDocumentSampleUrl(queued.id),
    templateFileName(template.name, template.edition, language, "pdf"),
  );
}
