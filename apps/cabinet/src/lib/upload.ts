/** Файл клиента для `POST /uploads` (контракт 0.2.0): до 10 МБ; скан акта — PDF или изображение. */
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

export type UploadProblem = 'tooLarge' | 'badType';

export function isScanFile(file: Pick<File, 'type' | 'name'>): boolean {
  return file.type === 'application/pdf' || file.type.startsWith('image/') || /\.(pdf|png|jpe?g|webp|heic)$/i.test(file.name);
}

/** Проверка до отправки: тот же отказ ERP (`FILE_TOO_LARGE`) клиент узнаёт сразу, а не после загрузки. */
export function scanProblem(file: Pick<File, 'type' | 'name' | 'size'>): UploadProblem | null {
  if (file.size > MAX_UPLOAD_BYTES) return 'tooLarge';
  return isScanFile(file) ? null : 'badType';
}
