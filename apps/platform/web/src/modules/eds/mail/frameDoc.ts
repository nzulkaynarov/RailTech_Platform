/**
 * HTML письма в изолированном фрейме (W18A-P2-4). Сервер уже очистил разметку по белому списку; здесь —
 * вторая стена: `sandbox` без `allow-scripts` (скрипты не выполнятся даже при ошибке очистки), строгий CSP
 * внутри `srcdoc`, внешние картинки без адреса, пока человек не нажал «Показать картинки» (трекинг-пиксели),
 * цитата свёрнута в `<details>` (работает без скриптов).
 *
 * `allow-same-origin` нужен только родителю — прочитать высоту содержимого и подогнать фрейм без внутренней
 * прокрутки; скрипты во фрейме запрещены и `sandbox`, и CSP (`default-src 'none'`), поэтому письмо не
 * получает доступа к странице (опасна связка `allow-scripts` + `allow-same-origin`, её здесь нет).
 * `allow-popups` — ссылки письма открываются в новой вкладке (`target=_blank`, `noopener`).
 */
export const MAIL_SANDBOX = "allow-same-origin allow-popups allow-popups-to-escape-sandbox";

export function mailCsp(showImages: boolean): string {
  const images = showImages ? "data: https:" : "data:";
  return `default-src 'none'; img-src ${images}; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'`;
}

/** Блоки цитаты: Gmail, Apple Mail / Thunderbird (`blockquote`), Yahoo, Proton. */
const QUOTE = "blockquote, div.gmail_quote, .yahoo_quoted, .protonmail_quote";

const FRAME_CSS = `
html{-webkit-text-size-adjust:100%;overflow:hidden}
body{margin:0;padding:0;font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:#1f1f1f;background:#fff;overflow-wrap:anywhere;word-break:break-word;overflow-y:hidden}
body *{max-width:100%}
img{max-width:100%!important;height:auto!important}
table{max-width:100%!important;table-layout:fixed}
td,th{word-break:break-word}
pre,code{white-space:pre-wrap}
a{color:#1668dc}
.rt-missing{display:inline-block;padding:2px 8px;border:1px dashed #8c8c8c;border-radius:4px;color:#595959;font-size:12px}
details.rt-q>summary{display:inline-block;margin:4px 0;padding:0 8px;border:1px solid #d9d9d9;border-radius:4px;color:#595959;cursor:pointer;list-style:none}
details.rt-q>summary::-webkit-details-marker{display:none}
details.rt-q[open]>summary{margin-bottom:8px}
`;

export interface FrameLabels {
  /** Язык интерфейса — `lang` документа письма (скринридеру) */
  lang: string;
  /** Подпись свёрнутой цитаты (`aria-label` у «…») */
  quote: string;
  /** Заглушка вместо потерянной встроенной картинки */
  missingImage: string;
}

function fold(doc: Document, labels: FrameLabels): void {
  const found = [...doc.body.querySelectorAll(QUOTE)];
  const top = found.filter((el) => el.parentElement?.closest(QUOTE) == null);
  for (const el of top) {
    const details = doc.createElement("details");
    details.className = "rt-q";
    const summary = doc.createElement("summary");
    summary.textContent = "…";
    summary.setAttribute("aria-label", labels.quote);
    details.append(summary);
    el.replaceWith(details);
    details.append(el);
  }
}

function images(doc: Document, showImages: boolean, labels: FrameLabels): void {
  for (const img of doc.body.querySelectorAll("img")) {
    const remote = img.getAttribute("data-rt-src");
    img.removeAttribute("data-rt-src");
    if (remote !== null && showImages) {
      img.setAttribute("src", remote.replace(/^http:/i, "https:"));
    }
    if (img.hasAttribute("data-rt-missing")) {
      const stub = doc.createElement("span");
      stub.className = "rt-missing";
      stub.textContent = img.getAttribute("alt") || labels.missingImage;
      img.replaceWith(stub);
    }
  }
}

/**
 * Документ для `srcdoc`: безопасный HTML сервера + CSP + стиль подгонки под ширину панели. До клика «Показать
 * картинки» адреса внешних картинок в документ не попадают вовсе.
 */
export function buildSrcDoc(html: string, showImages: boolean, labels: FrameLabels): string {
  const doc = new DOMParser().parseFromString(html, "text/html");
  fold(doc, labels);
  images(doc, showImages, labels);
  return (
    `<!doctype html><html lang="${labels.lang}"><head><meta charset="utf-8">` +
    `<meta http-equiv="Content-Security-Policy" content="${mailCsp(showImages)}">` +
    `<meta name="viewport" content="width=device-width, initial-scale=1">` +
    `<style>${FRAME_CSS}</style></head><body>${doc.body.innerHTML}</body></html>`
  );
}

/** Первые `max` непустых строк текста и признак «есть ещё» — для компактного превью в карточке. */
export function previewText(text: string, max: number): { shown: string; more: boolean } {
  const lines = text.split("\n");
  const keep: string[] = [];
  let filled = 0;
  for (const line of lines) {
    if (line.trim() !== "") {
      if (filled === max) return { shown: keep.join("\n").trimEnd(), more: true };
      filled += 1;
    }
    keep.push(line);
  }
  return { shown: text, more: false };
}
