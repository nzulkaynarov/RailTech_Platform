import { describe, expect, it } from 'vitest';

import { foldUz, searchHelpArticles } from '../lib/helpArticles';

describe('Uzbek help search: new and old alphabet are one spelling', () => {
  it('folds both alphabets to one key', () => {
    expect(foldUz("O'zbek")).toBe('özbek');
    expect(foldUz('Oʻzbek')).toBe('özbek');
    expect(foldUz('Gʻildirak')).toBe('ğildirak');
    expect(foldUz('shartnoma chek')).toBe('şartnoma çek');
    expect(foldUz('şartnoma çek')).toBe('şartnoma çek');
  });

  it('finds an article by a query in the old alphabet and in the new one', () => {
    const article = searchHelpArticles('', 'uz').find((a) => /[şçöğ]/i.test(a.content.uz.join(' ')));
    expect(article).toBeDefined();
    const word = (article?.content.uz.join(' ').match(/\p{L}*[şçöğ]\p{L}*/iu) ?? [''])[0];
    const oldSpelling = word.replace(/ö/g, "o'").replace(/ğ/g, "g'").replace(/ş/g, 'sh').replace(/ç/g, 'ch');
    expect(word).not.toBe('');
    expect(searchHelpArticles(word, 'uz').map((a) => a.id)).toContain(article?.id);
    expect(searchHelpArticles(oldSpelling, 'uz').map((a) => a.id)).toContain(article?.id);
  });
});
