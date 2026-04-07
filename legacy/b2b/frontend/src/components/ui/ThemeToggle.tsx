import React, { useEffect } from 'react';
import { Sun, Moon } from 'lucide-react';
import { useThemeStore } from '../../store/themeStore';

export const ThemeToggle: React.FC = () => {
    const { theme, toggleTheme } = useThemeStore();

    useEffect(() => {
        const root = window.document.documentElement;
        if (theme === 'dark') {
            root.classList.add('dark');
        } else {
            root.classList.remove('dark');
        }
    }, [theme]);

    return (
        <button
            onClick={toggleTheme}
            className="p-2 rounded-lg bg-muted hover:bg-accent text-muted-foreground transition-all"
            aria-label="Toggle theme"
        >
            {theme === 'light' ? (
                <Moon className="w-4 h-4" />
            ) : (
                <Sun className="w-4 h-4" />
            )}
        </button>
    );
};
