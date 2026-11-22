import { useEffect } from 'react';

/** Below this the visual viewport shrank for a browser toolbar, not for the on-screen keyboard. */
export const KEYBOARD_MIN_INSET = 120;

interface ViewportLike {
  height: number;
  offsetTop: number;
  /** Pinch zoom factor; 1 when not zoomed. */
  scale?: number;
}

/** Height the on-screen keyboard covers: layout viewport minus the visual one; 0 while it is closed. */
export function keyboardInsetOf(innerHeight: number, viewport: ViewportLike | null): number {
  if (!viewport) return 0;
  // A pinch zoom shrinks the visual viewport too, but it is not the keyboard
  if ((viewport.scale ?? 1) > 1.01) return 0;
  const inset = Math.round(innerHeight - viewport.height - viewport.offsetTop);
  return inset >= KEYBOARD_MIN_INSET ? inset : 0;
}

let users = 0;
let stop: (() => void) | null = null;

function start(): () => void {
  const root = document.documentElement;
  const viewport = window.visualViewport;
  const apply = () => {
    const inset = keyboardInsetOf(window.innerHeight, viewport);
    root.style.setProperty('--kb-inset', `${inset}px`);
    if (inset > 0) root.dataset.kb = 'open';
    else delete root.dataset.kb;
  };
  apply();
  viewport?.addEventListener('resize', apply);
  viewport?.addEventListener('scroll', apply);
  return () => {
    viewport?.removeEventListener('resize', apply);
    viewport?.removeEventListener('scroll', apply);
    root.style.removeProperty('--kb-inset');
    delete root.dataset.kb;
  };
}

/**
 * One shared keeper of the on-screen keyboard offset (ЕВ-0): while any consumer is mounted, `--kb-inset` on `<html>`
 * holds the covered height and `data-kb="open"` marks the open keyboard. The bottom sheet and the unsaved-changes bar
 * read the variable (`index.css`), so the action button is never hidden by the keyboard; the bottom nav yields its place.
 */
export function useKeyboardInset(): void {
  useEffect(() => {
    users += 1;
    if (users === 1) stop = start();
    return () => {
      users -= 1;
      if (users === 0) {
        stop?.();
        stop = null;
      }
    };
  }, []);
}
