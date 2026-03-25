import { describe, it, expect, beforeEach } from 'vitest';
import { useAuthStore } from '../authStore';

describe('authStore', () => {
  beforeEach(() => {
    // Reset store state before each test
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

    // Set some data
    state.setUser({
      id: '1',
      email: 'test@example.com',
      first_name: 'Test',
      last_name: 'User',
      role_code: 'CLIENT',
      kyc_status: 'L1_UNVERIFIED',
      company: null,
    });

    expect(useAuthStore.getState().user).not.toBeNull();

    // Logout
    state.logout();

    // Verify data is cleared
    expect(useAuthStore.getState().user).toBeNull();
    expect(useAuthStore.getState().role).toBeNull();
    expect(useAuthStore.getState().kyc_status).toBeNull();
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
  });

  it('should set user with correct role mapping', () => {
    const state = useAuthStore.getState();

    const user = {
      id: '1',
      email: 'test@example.com',
      first_name: 'Test',
      last_name: 'User',
      role_code: 'CLIENT',
      kyc_status: 'L2_VERIFIED' as const,
      company: null,
    };

    state.setUser(user);

    const currentState = useAuthStore.getState();
    expect(currentState.user).toEqual(user);
    expect(currentState.role).toBe('CLIENT');
    expect(currentState.kyc_status).toBe('L2_VERIFIED');
  });

  it('should map MANAGER role to SALES_MANAGER', () => {
    const state = useAuthStore.getState();

    const user = {
      id: '1',
      email: 'manager@example.com',
      first_name: 'Manager',
      last_name: 'User',
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      role_code: 'MANAGER' as any,
      kyc_status: null,
      company: null,
    };

    state.setUser(user);

    const currentState = useAuthStore.getState();
    expect(currentState.role).toBe('SALES_MANAGER');
  });

  it('should handle primary_company mapping', () => {
    const state = useAuthStore.getState();

    const company = { id: 'company-1', name: 'Test Company' };
    const user = {
      id: '1',
      email: 'test@example.com',
      first_name: 'Test',
      last_name: 'User',
      role_code: 'CLIENT',
      kyc_status: null,
      company: null,
      primary_company: company,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any;

    state.setUser(user);

    const currentState = useAuthStore.getState();
    expect(currentState.user?.company).toEqual(company);
  });
});
