// Тексты docs/kb/*.md (копия через `pnpm kb:sync`, равенство проверяет kbDocs.test.ts).
import example from "../../../generated/kb-docs/example.md?raw";
import format from "../../../generated/kb-docs/FORMAT.md?raw";
import prompt from "../../../generated/kb-docs/PROMPT.md?raw";

export const KB_FORMAT_MD: string = format;
export const KB_EXAMPLE_MD: string = example;
export const KB_EXAMPLE_FILENAME = "kb-example.md";
export const KB_PROMPT_MD: string = prompt;

/** Готовый промпт — содержимое блока ````text … ```` в PROMPT.md. */
export function kbPromptText(source: string = prompt): string {
  const match = /````text\n([\s\S]*?)\n````/.exec(source);
  return match?.[1] ?? source;
}

export function downloadText(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
