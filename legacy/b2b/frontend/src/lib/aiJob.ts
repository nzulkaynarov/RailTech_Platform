import { apiClient } from '@/api/client';

/**
 * ARCH-01 — client half of the async AI job pattern.
 *
 * The interactive AI endpoints no longer run the LLM call in the request path: they
 * return 202 {task_id} and the worker publishes the ORIGINAL response shape as the
 * Celery result. `runAiJob` posts, then polls GET sourcing/ai-status/<task_id>/ until
 * SUCCESS/FAILURE, so every api method keeps its existing return type — callers are
 * unaffected.
 *
 * Business-gate failures arrive as a SUCCESS result carrying {error: CODE}; they are
 * re-thrown as Error(CODE) so the central apiErrors.* map translates them exactly as
 * it did for the old synchronous 4xx bodies. Backend FAILURE always carries the stable
 * AI_JOB_FAILED code (never raw exception text).
 */

const POLL_INTERVAL_MS = 1500;
// Budget: compose worst case is 2 sequential 60s Claude calls + queue wait.
const POLL_BUDGET_MS = 150_000;
// A single transient blip (5xx / 429 / network) over an up-to-100-poll wait must not
// lose the job result — tolerate a few CONSECUTIVE failed polls before giving up.
const MAX_CONSECUTIVE_POLL_FAILURES = 3;

interface AiJobStatusResponse {
	task_id: string;
	status: string;
	result: Record<string, unknown> | null;
}

const sleep = (ms: number) => new Promise<void>((resolve) => { setTimeout(resolve, ms); });

export async function runAiJob<T>(post: () => Promise<{ task_id: string }>): Promise<T> {
	const { task_id: taskId } = await post();
	const deadline = Date.now() + POLL_BUDGET_MS;
	let consecutiveFailures = 0;
	while (Date.now() < deadline) {
		try {
			const { data } = await apiClient.get<AiJobStatusResponse>(`sourcing/ai-status/${taskId}/`);
			consecutiveFailures = 0;
			if (data.status === 'SUCCESS') {
				const result = (data.result ?? {}) as Record<string, unknown>;
				if (typeof result.error === 'string') throw new Error(result.error);
				return result as T;
			}
			if (data.status === 'FAILURE') {
				const message = data.result && typeof data.result.message === 'string' ? data.result.message : null;
				throw new Error(message || 'AI_JOB_FAILED');
			}
		} catch (pollError) {
			// Terminal outcomes above are plain Errors with a stable UPPER_SNAKE code —
			// rethrow them; only transport-level poll failures are tolerated.
			if (pollError instanceof Error && /^[A-Z][A-Z0-9_]+$/.test(pollError.message)) throw pollError;
			consecutiveFailures += 1;
			if (consecutiveFailures >= MAX_CONSECUTIVE_POLL_FAILURES) throw pollError;
		}
		await sleep(POLL_INTERVAL_MS);
	}
	throw new Error('AI_JOB_TIMEOUT');
}
