import { describe, it, expect } from 'vitest';

import { normalizeTemplateHtml, templateHtmlEquals } from '@/lib/templateHtml';

/**
 * The rich-text editor writes via `document.execCommand`, whose output is browser-specific junk.
 * `normalizeTemplateHtml` must fold that markup into the SAME allowlist the backend sanitiser
 * enforces (crm/services/document_placeholders.py) — so «what you see = what is stored».
 */
describe('normalizeTemplateHtml', () => {
  it('maps presentational tags to semantic ones (<b>→<strong>, <i>→<em>)', () => {
    expect(normalizeTemplateHtml('<b>hi</b> <i>there</i>')).toBe('<strong>hi</strong> <em>there</em>');
  });

  it('maps <div> to <p>', () => {
    expect(normalizeTemplateHtml('<div>line</div>')).toBe('<p>line</p>');
  });

  it('unwraps <span> and strips style/class/id attributes (execCommand junk)', () => {
    const dirty = '<span style="font-weight:700" class="x" id="y">bold-ish</span>';
    expect(normalizeTemplateHtml(dirty)).toBe('bold-ish');
  });

  it('unwraps disallowed tags but keeps their text (<font>)', () => {
    expect(normalizeTemplateHtml('<font color="red">kept</font>')).toBe('kept');
  });

  it('drops <script>/<style> content entirely', () => {
    expect(normalizeTemplateHtml('a<script>alert(1)</script>b')).toBe('ab');
    expect(normalizeTemplateHtml('<style>.x{}</style>text')).toBe('text');
  });

  it('strips on* event handlers', () => {
    // <a> survives (allowed) but the onclick handler and the disallowed target attr are dropped.
    const out = normalizeTemplateHtml('<a href="https://x.io" onclick="evil()" target="_blank">t</a>');
    expect(out).toBe('<a href="https://x.io">t</a>');
  });

  it('drops javascript:/data: hrefs, keeps http(s)/mailto/relative', () => {
    expect(normalizeTemplateHtml('<a href="javascript:alert(1)">x</a>')).toBe('<a>x</a>');
    expect(normalizeTemplateHtml('<a href="data:text/html,evil">x</a>')).toBe('<a>x</a>');
    expect(normalizeTemplateHtml('<a href="https://ok.io">x</a>')).toBe('<a href="https://ok.io">x</a>');
    expect(normalizeTemplateHtml('<a href="mailto:a@b.io">x</a>')).toBe('<a href="mailto:a@b.io">x</a>');
  });

  it('preserves list, heading and table structure within the allowlist', () => {
    const rich = '<h3>Title</h3><ul><li>one</li><li>two</li></ul>'
      + '<table><thead><tr><th>H</th></tr></thead><tbody><tr><td>C</td></tr></tbody></table>';
    expect(normalizeTemplateHtml(rich)).toBe(rich);
  });

  it('keeps {{placeholder}} tokens verbatim as text', () => {
    expect(normalizeTemplateHtml('<p>Deal {{deal.number}} for {{counterparty.name}}</p>'))
      .toBe('<p>Deal {{deal.number}} for {{counterparty.name}}</p>');
  });

  it('escapes stray angle brackets in text content', () => {
    expect(normalizeTemplateHtml('<p>2 < 3 & 4 > 1</p>')).toBe('<p>2 &lt; 3 &amp; 4 &gt; 1</p>');
  });

  it('normalises void tags to self-closing form', () => {
    expect(normalizeTemplateHtml('a<br>b')).toBe('a<br />b');
  });

  it('is idempotent — normalising twice yields the same output (fixed point)', () => {
    const messy = '<div style="x"><b>A</b><span>B</span><i>C</i></div>';
    const once = normalizeTemplateHtml(messy);
    expect(normalizeTemplateHtml(once)).toBe(once);
  });

  it('templateHtmlEquals ignores presentational differences', () => {
    expect(templateHtmlEquals('<b>x</b>', '<strong>x</strong>')).toBe(true);
    expect(templateHtmlEquals('<p>x</p>', '<p>y</p>')).toBe(false);
  });
});
