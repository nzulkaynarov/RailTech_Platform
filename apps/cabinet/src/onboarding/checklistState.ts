export const ONBOARDING_DISMISSED_KEY = 'rt-cab-onboarding-dismissed';

export function isChecklistDismissed(): boolean {
  try {
    return localStorage.getItem(ONBOARDING_DISMISSED_KEY) === 'true';
  } catch {
    return false;
  }
}

export function dismissChecklist(): void {
  try {
    localStorage.setItem(ONBOARDING_DISMISSED_KEY, 'true');
  } catch {
    // ignore
  }
}
