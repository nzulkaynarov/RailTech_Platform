import { describe, it, expect, beforeEach } from 'vitest';
import { useUserStore } from '../userStore';

describe('userStore', () => {
  beforeEach(() => {
    // Reset store to defaults
    useUserStore.setState({
      screen: 'loading',
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
        country: '',
        city: '',
        logoUrl: null,
      },
    });
  });

  it('should initialize with default values', () => {
    const state = useUserStore.getState();
    expect(state.screen).toBe('loading');
    // ERP — бэк-офис одной компании (M1-ERP-02 волна 3): контекста «покупатель / продавец» нет.
    expect('activeStatus' in state).toBe(false);
    expect('setActiveStatus' in state).toBe(false);
    expect(state.profile.firstName).toBe('');
    expect(state.company.id).toBeNull();
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
    expect(state.company.country).toBe('');
  });
});
