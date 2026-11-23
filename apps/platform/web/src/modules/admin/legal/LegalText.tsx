import type { LegalContent, LegalLangText } from "../../../shared/api/generated/model";

export type LegalLang = keyof LegalLangText;

/** Абзацы и списки из простого текста раздела: подряд идущие «— …» собираются в один список. Разметки из текста нет. */
function Blocks({ text }: { text: string }) {
  const blocks: { list: boolean; lines: string[] }[] = [];
  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    const bullet = line.startsWith("— ");
    const last = blocks[blocks.length - 1];
    const value = bullet ? line.slice(2) : line;
    if (bullet && last?.list) last.lines.push(value);
    else blocks.push({ list: bullet, lines: [value] });
  }
  return (
    <>
      {blocks.map((block, index) =>
        block.list ? (
          <ul key={index}>
            {block.lines.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        ) : (
          <p key={index}>{block.lines[0]}</p>
        ),
      )}
    </>
  );
}

/** Текст редакции на одном языке: заголовок, вводный абзац, разделы. Подстановки реквизитов уже заполнены сервером. */
export function LegalText({ content, lang }: { content: LegalContent; lang: LegalLang }) {
  return (
    <article className="pf-legal-doc" lang={lang}>
      <h2 style={{ margin: "0 0 8px", fontSize: 16, lineHeight: "24px", fontWeight: 600 }}>
        {content.title[lang]}
      </h2>
      {content.lead[lang] ? <p className="pf-hint">{content.lead[lang]}</p> : null}
      {content.sections.map((section, index) => (
        <section key={index}>
          <h3>{section.title[lang]}</h3>
          <Blocks text={section.body[lang]} />
        </section>
      ))}
    </article>
  );
}
