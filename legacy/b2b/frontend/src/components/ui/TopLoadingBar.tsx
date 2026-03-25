import React, { useState, useEffect, useRef } from 'react';
import { useLoadingStore } from '../../store/loadingStore';

/**
 * NProgress-style thin loading bar at the top of the page.
 * Shows during initial page load and data fetching.
 * Non-intrusive: 2px height, positioned above all content.
 */
export const TopLoadingBar: React.FC = () => {
    const isLoading = useLoadingStore(s => s.isPageLoading);
    const [progress, setProgress] = useState(0);
    const [visible, setVisible] = useState(false);
    const timers = useRef<number[]>([]);

    const clearTimers = () => {
        timers.current.forEach(id => window.clearTimeout(id));
        timers.current = [];
    };

    useEffect(() => {
        clearTimers();

        if (isLoading) {
            setVisible(true);
            setProgress(0);
            // Быстрый старт, потом медленное ожидание
            timers.current.push(window.setTimeout(() => setProgress(15), 50));
            timers.current.push(window.setTimeout(() => setProgress(40), 300));
            timers.current.push(window.setTimeout(() => setProgress(65), 800));
            timers.current.push(window.setTimeout(() => setProgress(80), 1500));
            timers.current.push(window.setTimeout(() => setProgress(88), 2500));
        } else {
            // Завершение: прыжок до 100%, потом исчезновение
            setProgress(100);
            timers.current.push(window.setTimeout(() => {
                setVisible(false);
            }, 400));
            timers.current.push(window.setTimeout(() => {
                setProgress(0);
            }, 450));
        }

        return clearTimers;
    }, [isLoading]);

    if (!visible && progress === 0) return null;

    return (
        <div
            className="fixed top-0 left-0 right-0 z-[9999] h-[2px] pointer-events-none"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={progress}
            aria-label="Загрузка данных"
        >
            <div
                className="h-full bg-blue-500 top-loading-bar"
                style={{
                    width: `${progress}%`,
                    opacity: visible ? 1 : 0,
                    transition: isLoading
                        ? 'width 0.6s cubic-bezier(0.1, 0.8, 0.3, 1)'
                        : 'width 0.2s ease-in, opacity 0.3s ease-in 0.1s',
                }}
            />
        </div>
    );
};
