/**
 * Хуки командной палитры (⌘K): горячая клавиша и состояние. Отдельный модуль — Fast Refresh.
 */

import { useEffect, useState } from 'react';

export function useCommandPaletteShortcut(onOpen: () => void) {
    useEffect(() => {
        const handler = (e: KeyboardEvent) => {
            if ((e.key === 'k' || e.key === 'K') && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                onOpen();
            }
        };
        window.addEventListener('keydown', handler);
        return () => window.removeEventListener('keydown', handler);
    }, [onOpen]);
}

export function useCommandPaletteState(): [boolean, (v: boolean) => void, () => void] {
    const [open, setOpen] = useState(false);
    const openPalette = () => setOpen(true);
    return [open, setOpen, openPalette];
}
