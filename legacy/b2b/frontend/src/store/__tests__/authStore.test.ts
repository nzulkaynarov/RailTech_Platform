import { describe, it, expect, beforeEach } from 'vitest';
import { useAuthStore } from '../authStore';

const mockUser = (overrides = {}) => ({
  id: 1,
  username: 'testuser',
  email: 'test@example.com',
  first_name: 'Test',
  last_name: 'User',
  phone: '+1234567890',
  role_code: 'CLIENT',
  kyc_status: 'L1_UNVERIFIED',
  company: undefined,
  ...overrides,
});

describe('authStore', () => {
  beforeEach(() => {
    const { logout } = useAuthStore.getState();
    logout();
  });

  it('should initialize with default values', () => {
    const state = useAuthStore.getState();
    expect(state.user).toBeNull();
    expect(state.role).toBeNull();
    expect(state.accessToken).toBeNull();
    expect(state.refreshToken).toBeNull();
    expect(state.isAuthenticated).toBe(false);
    expect(state.isLoading).toBe(false);
  });

  it('should logout and clear all user data', () => {
    const state = useAuthStore.getState();

    state.setUser(mockUser());
    expect(useAuthStore.getState().user).not.toBeNull();

    state.logout();

    expect(useAuthStore.getState().user).toBeNull();
    expect(useAuthStore.getState().role).toBeNull();
    expect(useAuthStore.getState().kyc_status).toBeNull();
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
  });

  it('should set user with correct role mapping', () => {
    const state = useAuthStore.getState();

    const user = mockUser({ kyc_status: 'L2_VERIFIED' });
    state.setUser(user);

    const currentState = useAuthStore.getState();
    expect(currentState.user).toEqual(user);
    expect(currentState.role).toBe('CLIENT');
    expect(currentState.kyc_status).toBe('L2_VERIFIED');
  });

  it('should map MANAGER role to SALES_MANAGER', () => {
    const state = useAuthStore.getState();

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const user = mockUser({ role_code: 'MANAGER' as any, kyc_status: null });
    state.setUser(user);

    const currentState = useAuthStore.getState();
    expect(currentState.role).toBe('SALES_MANAGER');
  });

  it('should handle primary_company mapping', () => {
    const state = useAuthStore.getState();

    const company = { id: 1, name: 'Test Company' };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const user = mockUser({ kyc_status: null, primary_company: company }) as any;
    state.setUser(user);

    const currentState = useAuthStore.getState();
    expect(currentState.user?.company).toEqual(company);
  });
});
