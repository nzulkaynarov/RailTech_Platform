import { useApiHealth } from "../hooks/useApiHealth";

// Каркас Фазы 0. Refine, Ant Design, i18n (ru/uz/en) и страницы — Фаза 4 (PLAN.md).
export function App() {
  const health = useApiHealth();

  return (
    <main>
      <h1>RailTech CRM</h1>
      <p>
        API: <code data-testid="api-health">{health}</code>
      </p>
    </main>
  );
}
