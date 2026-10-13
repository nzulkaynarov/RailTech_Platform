import { create } from 'zustand';
import { crmApi } from '../api/crmApi';

interface TaskProgress {
    current: number;
    total: number;
}

/** Final payload of a finished import task (process_excel_import return). */
export interface TaskResult {
    items_processed?: number;
    merged?: number;
}

interface ActiveTask {
    id: string;
    type: 'excel_import' | 'catalog_import';
    status: 'PENDING' | 'PROGRESS' | 'SUCCESS' | 'FAILURE';
    progress: TaskProgress | null;
    result: TaskResult | null;
    error: string | null;
}

interface TaskState {
    tasks: { [id: string]: ActiveTask };
    activeTaskIds: string[];
    /** Map of task ID → interval ID for cleanup */
    _intervals: { [id: string]: ReturnType<typeof setInterval> };
    addTask: (id: string, type: ActiveTask['type']) => void;
    updateTask: (id: string, updates: Partial<ActiveTask>) => void;
    removeTask: (id: string) => void;
    pollTask: (id: string) => void;
    /** Stop polling for a specific task (cleanup) */
    stopPolling: (id: string) => void;
    /** Stop all polling (call on unmount) */
    stopAllPolling: () => void;
}

export const useTaskStore = create<TaskState>((set, get) => ({
    tasks: {},
    activeTaskIds: [],
    _intervals: {},

    addTask: (id, type) => {
        set((state) => ({
            tasks: {
                ...state.tasks,
                [id]: {
                    id,
                    type,
                    status: 'PENDING',
                    progress: null,
                    result: null,
                    error: null,
                },
            },
            activeTaskIds: [...state.activeTaskIds, id],
        }));
        get().pollTask(id);
    },

    updateTask: (id, updates) => {
        set((state) => ({
            tasks: {
                ...state.tasks,
                [id]: { ...state.tasks[id], ...updates },
            },
        }));
    },

    removeTask: (id) => {
        get().stopPolling(id);
        set((state) => {
            const newTasks = { ...state.tasks };
            delete newTasks[id];
            return {
                tasks: newTasks,
                activeTaskIds: state.activeTaskIds.filter((taskId) => taskId !== id),
            };
        });
    },

    stopPolling: (id) => {
        const intervals = get()._intervals;
        if (intervals[id]) {
            clearInterval(intervals[id]);
            set((state) => {
                const newIntervals = { ...state._intervals };
                delete newIntervals[id];
                return { _intervals: newIntervals };
            });
        }
    },

    stopAllPolling: () => {
        const intervals = get()._intervals;
        Object.values(intervals).forEach(clearInterval);
        set({ _intervals: {} });
    },

    pollTask: (id) => {
        let attempts = 0;
        const maxAttempts = 150; // 5 minutes max (150 × 2s)

        const interval = setInterval(async () => {
            attempts++;

            if (attempts > maxAttempts) {
                get().updateTask(id, { status: 'FAILURE', error: 'Timeout: task took too long' });
                get().stopPolling(id);
                setTimeout(() => get().removeTask(id), 8000);
                return;
            }

            try {
                const result = await crmApi.getTaskStatus(id);

                if (result.status === 'PROGRESS' && result.meta) {
                    get().updateTask(id, {
                        status: 'PROGRESS',
                        progress: result.meta as TaskProgress
                    });
                } else if (result.status === 'SUCCESS') {
                    get().updateTask(id, { status: 'SUCCESS', progress: null, result: (result.result as TaskResult) ?? null });
                    get().stopPolling(id);
                    setTimeout(() => get().removeTask(id), 5000);
                } else if (result.status === 'FAILURE') {
                    const msg = (result.result as { message?: string })?.message || 'Import failed';
                    get().updateTask(id, { status: 'FAILURE', error: msg });
                    get().stopPolling(id);
                    setTimeout(() => get().removeTask(id), 8000);
                }
            } catch (err) {
                console.error('Task polling error:', err);
                get().updateTask(id, { status: 'FAILURE', error: 'errors.network' });
                get().stopPolling(id);
                setTimeout(() => get().removeTask(id), 8000);
            }
        }, 2000);

        // Store interval reference for cleanup
        set((state) => ({
            _intervals: { ...state._intervals, [id]: interval },
        }));
    },
}));
