/**
 * Document-template HTML normalisation (rich-text editor, wave T2).
 *
 * The WYSIWYG editor (`RichTextTemplateEditor`) writes with `document.execCommand`,
 * whose output is browser-dependent junk: `<b>`/`<i>` presentational tags, `<span style>`
 * wrappers, `class`/`id` attributes, `<font>`, stray `<div>`s. If that raw markup were saved,
 * the backend allowlist sanitiser (`crm/services/document_placeholders.py::sanitize_template_html`)
 * would strip a chunk of it — so «what the author sees» would drift from «what is stored».
 *
 * `normalizeTemplateHtml` closes that gap on the client: it serialises the DOM into the SAME
 * allowlist the backend enforces, mapping presentational tags to semantic ones
 * (`<b>`→`<strong>`, `<i>`→`<em>`, `<div>`→`<p>`), unwrapping `<span>`/`<font>` and any other
 * disallowed tag (keeping their text), dropping `<script>`/`<style>` bodies, and pruning every
 * attribute outside the per-tag allowlist (incl. `on*` handlers, `style`, `class`).
 *
 * The output is therefore a fixed point of the backend sanitiser: visible content survives the
 * round-trip unchanged. Placeholders (`{{code}}`) are plain text nodes — preserved verbatim.
 *
 * This module intentionally has ZERO runtime dependencies (npm audit is a hard CI gate) — it uses
 * only the platform `DOMParser`, available in browsers and in the jsdom test environment.
 */

// Presentational → semantic renames applied before the allowlist check.
const TAG_RENAME: Record<string, string> = {
  b: 'strong',
  strong: 'strong',
  i: 'em',
  em: 'em',
  div: 'p',
};

// Tags kept in the output (post-rename). Mirrors backend `_ALLOWED_TAGS` minus the
// presentational/embed tags the editor never emits (`u` kept — backend allows it; `span`/`img`
// are intentionally NOT here so they get unwrapped/dropped rather than surviving as noise).
const ALLOWED_TAGS = new Set([
  'p', 'br', 'h1', 'h2', 'h3', 'h4', 'strong', 'em', 'u',
  'ul', 'ol', 'li', 'table', 'thead', 'tbody', 'tr', 'td', 'th', 'a', 'hr',
]);

// Self-closing tags (no children, no closing tag). Mirrors backend `_VOID_TAGS` (sans img).
const VOID_TAGS = new Set(['br', 'hr']);

// Tags whose CONTENT is dropped entirely (never unwrapped — their text is not author content).
const DROP_WITH_CONTENT = new Set(['script', 'style', 'iframe', 'object', 'embed', 'head', 'title']);

// Per-tag attribute allowlist (post-rename tag name). Mirrors backend `_ALLOWED_ATTRS`.
const ALLOWED_ATTRS: Record<string, readonly string[]> = {
  a: ['href', 'title'],
  td: ['colspan', 'rowspan'],
  th: ['colspan', 'rowspan'],
};

// href URL policy — must match backend `_SAFE_HREF_RE` (no data:/javascript:/vbscript:).
const SAFE_HREF_RE = /^(https?:|mailto:|tel:|\/|#)/i;

function escapeText(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function escapeAttr(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function serializeAttrs(tag: string, element: Element): string {
  const allowed = ALLOWED_ATTRS[tag];
  if (!allowed) return '';
  const parts: string[] = [];
  for (const name of allowed) {
    if (!element.hasAttribute(name)) continue;
    const rawValue = (element.getAttribute(name) ?? '').trim();
    if (name === 'href' && !SAFE_HREF_RE.test(rawValue)) continue; // drop javascript:/data:/unknown
    if (!rawValue) continue;
    parts.push(` ${name}="${escapeAttr(rawValue)}"`);
  }
  return parts.join('');
}

const TEXT_NODE = 3;
const ELEMENT_NODE = 1;

function serializeNode(node: Node, out: string[]): void {
  if (node.nodeType === TEXT_NODE) {
    out.push(escapeText(node.textContent ?? ''));
    return;
  }
  if (node.nodeType !== ELEMENT_NODE) return;

  const element = node as Element;
  const rawTag = element.tagName.toLowerCase();
  if (DROP_WITH_CONTENT.has(rawTag)) return;

  const tag = TAG_RENAME[rawTag] ?? rawTag;

  // Disallowed tag (span, font, unknowns): unwrap — keep the children's text, drop the wrapper.
  if (!ALLOWED_TAGS.has(tag)) {
    element.childNodes.forEach((child) => serializeNode(child, out));
    return;
  }

  if (VOID_TAGS.has(tag)) {
    out.push(`<${tag} />`);
    return;
  }

  out.push(`<${tag}${serializeAttrs(tag, element)}>`);
  element.childNodes.forEach((child) => serializeNode(child, out));
  out.push(`</${tag}>`);
}

/**
 * Return `html` normalised into the backend allowlist: a fixed point of `sanitize_template_html`.
 * Accepts either a raw HTML string (parsed via DOMParser) or an already-parsed root Element.
 */
export function normalizeTemplateHtml(input: string | Element): string {
  let root: Element;
  if (typeof input === 'string') {
    const doc = new DOMParser().parseFromString(`<body>${input}</body>`, 'text/html');
    root = doc.body;
  } else {
    root = input;
  }
  const out: string[] = [];
  root.childNodes.forEach((child) => serializeNode(child, out));
  return out.join('').trim();
}

/** True if the two HTML strings are equal AFTER normalisation (visible content identical). */
export function templateHtmlEquals(left: string, right: string): boolean {
  return normalizeTemplateHtml(left) === normalizeTemplateHtml(right);
}
