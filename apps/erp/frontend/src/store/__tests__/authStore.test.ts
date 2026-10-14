import { describe, it, expect, beforeEach } from 'vitest';
import { useAuthStore } from '../authStore';

const mockUser = (overrides = {}) => ({
  id: 1,
  username: 'testuser',
  email: 'test@example.com',
  first_name: 'Test',
  last_name: 'User',
  phone: '+1234567890',
  role_code: 'USER',
  company: undefined,
  ...overrides,
});

describe('authStore', () => {
  beforeEach(async () => {
    await useAuthStore.getState().logout();
  });

  it('should initialize with default values', () => {
    const state = useAuthStore.getState();
    expect(state.user).toBeNull();
    expect(state.accessToken).toBeNull();
    expect(state.isAuthenticated).toBe(false);
    expect(state.isLoading).toBe(false);
  });

  it('should logout and clear all user data', async () => {
    const state = useAuthStore.getState();

    state.setUser(mockUser());
    expect(useAuthStore.getState().user).not.toBeNull();

    await state.logout();

    expect(useAuthStore.getState().user).toBeNull();
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
  });

  it('should keep the user from setUser', () => {
    const state = useAuthStore.getState();

    const user = mockUser({ role_code: 'USER' });
    state.setUser(user);

    const currentState = useAuthStore.getState();
    expect(currentState.user).toEqual(user);
  });

  it('should handle primary_company mapping', () => {
    const state = useAuthStore.getState();

    const company = { id: 1, name: 'Test Company' };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const user = mockUser({ primary_company: company }) as any;
    state.setUser(user);

    const currentState = useAuthStore.getState();
    expect(currentState.user?.company).toEqual(company);
  });
});
