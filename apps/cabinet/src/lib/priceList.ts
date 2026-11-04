import { getPriceTemplate } from '@/api/portal';
import { saveBlob } from '@/lib/download';

/** Размер файла прайса — как у сотрудника (ERP: 20 МБ, `.xlsx`). */
export const PRICE_LIST_MAX_BYTES = 20 * 1024 * 1024;

export type FileProblem = 'badType' | 'tooLarge';

export function priceFileProblem(file: Pick<File, 'name' | 'size'>): FileProblem | null {
  if (!/\.xlsx$/i.test(file.name)) return 'badType';
  return file.size > PRICE_LIST_MAX_BYTES ? 'tooLarge' : null;
}

/** Скачать шаблон прайса и сохранить как файл (тот же шаблон, что у сотрудника). */
export async function downloadTemplate(onError: (message: string) => void, message: string): Promise<void> {
  try {
    saveBlob(await getPriceTemplate(), 'price-template.xlsx');
  } catch {
    onError(message);
  }
}
