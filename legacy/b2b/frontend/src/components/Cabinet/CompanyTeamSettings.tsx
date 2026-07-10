/**
 * Façade — the 685-line monolith was split into the Settings/team package
 * (spec PR 4, file-length rule «max 500»). This thin component keeps the existing
 * import path (SettingsPage and any future callers) working unchanged.
 * (A plain `export ... from` re-export trips react-refresh/only-export-components,
 * so the façade is a real component.)
 */
import { CompanyTeamSettings as TeamSettingsSection } from '@/components/Settings/team/CompanyTeamSettings';

export function CompanyTeamSettings() {
  return <TeamSettingsSection />;
}

export default CompanyTeamSettings;
