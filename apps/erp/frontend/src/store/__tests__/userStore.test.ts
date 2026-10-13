import { describe, it, expect, beforeEach } from 'vitest';
import { useUserStore } from '../userStore';

describe('userStore', () => {
  beforeEach(() => {
    // Reset store to defaults
    useUserStore.setState({
      screen: 'onboarding',
      activeStatus: 'BUYER',
      profile: {
        firstName: '',
        lastName: '',
        patronymic: '',
        email: '',
        phone: '',
        position: '',
        avatarInitials: '',
        avatarUrl: null,
      },
      company: {
        id: null,
        name: '',
        inn: '',
        kycStatus: 'not_started',
        country: '',
        city: '',
        logoUrl: null,
        statusEntries: [],
      },
    });
  });

  it('should initialize with default values', () => {
    const state = useUserStore.getState();
    expect(state.screen).toBe('onboarding');
    // Pre-auth default context is the narrowest/safest side (BUYER); see userStore.ts.
    expect(state.activeStatus).toBe('BUYER');
    expect(state.profile.firstName).toBe('');
    expect(state.company.id).toBeNull();
  });

  it('should update activeStatus via setActiveStatus', () => {
    const { setActiveStatus } = useUserStore.getState();
    setActiveStatus('BUYER');
    expect(useUserStore.getState().activeStatus).toBe('BUYER');
  });

  it('should partially update profile via updateProfile', () => {
    const { updateProfile } = useUserStore.getState();
    updateProfile({ firstName: 'Test', email: 'test@example.com' });

    const state = useUserStore.getState();
    expect(state.profile.firstName).toBe('Test');
    expect(state.profile.email).toBe('test@example.com');
    // Other fields remain default
    expect(state.profile.lastName).toBe('');
  });

  it('should partially update company via updateCompany', () => {
    const { updateCompany } = useUserStore.getState();
    updateCompany({ name: 'RailTech', inn: '123456789' });

    const state = useUserStore.getState();
    expect(state.company.name).toBe('RailTech');
    expect(state.company.inn).toBe('123456789');
    // Other fields remain default
    expect(state.company.kycStatus).toBe('not_started');
  });

  it('should keep valid CompanyStatus types', () => {
    const { setActiveStatus } = useUserStore.getState();

    setActiveStatus('SELLER');
    expect(useUserStore.getState().activeStatus).toBe('SELLER');

    setActiveStatus('SELLER');
    expect(useUserStore.getState().activeStatus).toBe('SELLER');

    setActiveStatus('BUYER');
    expect(useUserStore.getState().activeStatus).toBe('BUYER');
  });
});
