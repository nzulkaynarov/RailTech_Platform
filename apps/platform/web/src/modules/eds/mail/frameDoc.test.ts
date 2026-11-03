import { describe, expect, it } from "vitest";

import { MAIL_SANDBOX, buildSrcDoc, mailCsp, previewText } from "./frameDoc";

const LABELS = { lang: "ru", quote: "Показать цитату", missingImage: "Картинка недоступна" };
const REMOTE = "https://cdn.example.test/banner.png?id=7";

describe("HTML письма во фрейме (P2-4)", () => {
  it("sandbox без allow-scripts; CSP запрещает всё, кроме встроенных стилей и картинок", () => {
    expect(MAIL_SANDBOX.split(" ")).not.toContain("allow-scripts");
    expect(MAIL_SANDBOX).toContain("allow-popups");
    const csp = mailCsp(false);
    expect(csp).toContain("default-src 'none'");
    expect(csp).toContain("style-src 'unsafe-inline'");
    expect(csp).toContain("img-src data:");
    expect(csp).not.toContain("https:");
    expect(csp).not.toContain("script-src");
    expect(mailCsp(true)).toContain("img-src data: https:");
  });

  it("srcdoc несёт CSP и подгонку под ширину; внешняя картинка до клика — без адреса вообще", () => {
    const html = `<table width="600"><tr><td><img data-rt-src="${REMOTE}" width="1" height="1"></td></tr></table>`;
    const doc = buildSrcDoc(html, false, LABELS);
    expect(doc).toContain('http-equiv="Content-Security-Policy"');
    expect(doc).toContain("img-src data:;");
    expect(doc).toContain("max-width:100%!important");
    expect(doc).toContain("table-layout:fixed");
    expect(doc).toContain("overflow-wrap:anywhere");
    expect(doc).not.toContain("cdn.example.test");
    expect(doc).not.toContain("data-rt-src");
    expect(doc).not.toMatch(/<img[^>]*\ssrc=/);
  });

  it("после клика адрес становится src, http поднимается до https", () => {
    const doc = buildSrcDoc(
      `<img data-rt-src="${REMOTE}"><img data-rt-src="http://cdn.example.test/b.png">`,
      true,
      LABELS,
    );
    expect(doc).toContain(`src="${REMOTE}"`);
    expect(doc).toContain('src="https://cdn.example.test/b.png"');
    expect(doc).toContain("img-src data: https:;");
    expect(doc).not.toContain("data-rt-src");
  });

  it("встроенная картинка data: остаётся как есть до и после клика", () => {
    const html = '<img src="data:image/png;base64,AAAA" alt="Лого">';
    expect(buildSrcDoc(html, false, LABELS)).toContain('src="data:image/png;base64,AAAA"');
  });

  it("потерянная встроенная картинка — заглушка с подписью, а не пустое место", () => {
    const doc = buildSrcDoc('<img data-rt-missing="1" alt="Лого компании">', false, LABELS);
    expect(doc).toContain('<span class="rt-missing">Лого компании</span>');
    expect(doc).not.toContain("<img");
    expect(buildSrcDoc("<img data-rt-missing=1>", false, LABELS)).toContain("Картинка недоступна");
  });

  it("цитата сворачивается в details с «…»; вложенные цитаты — один раз", () => {
    const html =
      "<p>Ответ</p>" +
      '<div class="gmail_quote"><div>On Mon wrote:</div><blockquote>1<blockquote>2</blockquote></blockquote></div>';
    const doc = buildSrcDoc(html, false, LABELS);
    expect(doc.match(/<details class="rt-q">/g)).toHaveLength(1);
    expect(doc).toContain('<summary aria-label="Показать цитату">…</summary>');
    expect(doc.indexOf("Ответ")).toBeLessThan(doc.indexOf("<details"));
  });

  it("скрипты из разметки не оживают: DOMParser инертен, а теги без обработчиков не добавляются", () => {
    const doc = buildSrcDoc("<p>текст</p>", false, LABELS);
    expect(doc).not.toMatch(/<script/i);
    expect(doc).not.toMatch(/\son\w+=/i);
  });
});

describe("Превью текста письма (P2-4)", () => {
  it("первые N непустых строк и признак «есть ещё»", () => {
    const text = "1\n2\n\n3\n4\n5";
    expect(previewText(text, 3)).toEqual({ shown: "1\n2\n\n3", more: true });
    expect(previewText(text, 5)).toEqual({ shown: text, more: false });
    expect(previewText(text, 9)).toEqual({ shown: text, more: false });
    expect(previewText("", 3)).toEqual({ shown: "", more: false });
  });
});
