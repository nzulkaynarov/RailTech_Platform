import { Fragment } from 'react';

import type { LegalEdition, LegalLang } from '@/api/portal';

/**
 * Текст одного документа Кабинета на выбранном языке: заголовок, вводный абзац и разделы. Тело раздела — простой текст:
 * абзацы через перевод строки, пункты списка начинаются с «— » (подстановки реквизитов компании сервер уже заполнил).
 * Чужой разметки нет: текст выводится как текст, не как HTML.
 */
export function LegalDocument({ edition, lang, headingLevel = 2 }: { edition: LegalEdition; lang: LegalLang; headingLevel?: 1 | 2 }) {
  const Heading = (headingLevel === 1 ? 'h1' : 'h2') as 'h1' | 'h2';
  const SectionHeading = (headingLevel === 1 ? 'h2' : 'h3') as 'h2' | 'h3';
  return (
    <article className="flex flex-col gap-4" lang={lang}>
      <header className="flex flex-col gap-2">
        <Heading className="text-lg font-semibold">{edition.title[lang]}</Heading>
        {edition.lead[lang] ? <p className="text-sm text-muted-foreground">{edition.lead[lang]}</p> : null}
      </header>
      {edition.sections.map((section, index) => (
        <section key={index} className="flex flex-col gap-2">
          <SectionHeading className="text-base font-semibold">{section.title[lang]}</SectionHeading>
          <Blocks text={section.body[lang]} />
        </section>
      ))}
    </article>
  );
}

const BULLET = '— ';

/** Абзацы и маркированные списки из простого текста: подряд идущие «— …» собираются в один список. */
function Blocks({ text }: { text: string }) {
  const blocks: Array<{ type: 'p' | 'ul'; lines: string[] }> = [];
  for (const line of text.split('\n')) {
    if (!line.trim()) continue;
    const bullet = line.startsWith(BULLET);
    const last = blocks[blocks.length - 1];
    if (bullet && last?.type === 'ul') last.lines.push(line.slice(BULLET.length));
    else blocks.push({ type: bullet ? 'ul' : 'p', lines: [bullet ? line.slice(BULLET.length) : line] });
  }
  return (
    <Fragment>
      {blocks.map((block, index) =>
        block.type === 'ul' ? (
          <ul key={index} className="ml-5 list-disc text-sm leading-relaxed">
            {block.lines.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        ) : (
          <p key={index} className="text-sm leading-relaxed">
            {block.lines[0]}
          </p>
        ),
      )}
    </Fragment>
  );
}
