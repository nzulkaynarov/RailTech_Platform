import React from 'react';
import { Navigate, Outlet } from 'react-router-dom';
import { useAuthStore } from '../../store/authStore';
import { Loader2 } from 'lucide-react';
import { UserRole } from '../../store/authStore';

interface ProtectedRouteProps {
    allowedRoles: UserRole[];
}

export const ProtectedRoute: React.FC<ProtectedRouteProps> = ({
    allowedRoles,
}) => {
    const { isAuthenticated, role, isLoading, kyc_status } = useAuthStore();

    if (isLoading) {
        return (
            <div className="flex h-screen items-center justify-center bg-background">
                <div className="flex flex-col items-center gap-4">
                    <Loader2 className="w-10 h-10 text-primary animate-spin" />
                    <p className="text-muted-foreground text-sm font-medium tracking-widest uppercase">Проверка доступа...</p>
                </div>
            </div>
        );
    }

    if (!isAuthenticated) {
        return <Navigate to="/login" replace />;
    }

    // New User Onboarding Check
    if (role === 'CLIENT') {
        if (kyc_status === 'L1_UNVERIFIED' && window.location.pathname !== '/auth/complete-profile') {
            return <Navigate to="/auth/complete-profile" replace />;
        }
        if (kyc_status === 'PROFILE_SUBMITTED' && window.location.pathname !== '/cabinet/home') {
            // Allow them to see home but maybe show limited info or a banner
            return <Navigate to="/cabinet/home" replace />;
        }
    }

    if (!role) {
        // No role assigned — send to login
        return <Navigate to="/login" replace />;
    }

    if (!allowedRoles.includes(role)) {
        // Redirect to appropriate home by role
        if (role === 'CLIENT') return <Navigate to="/cabinet/home" replace />;
        if (role === 'ADMIN') return <Navigate to="/admin/home" replace />;
        // SALES_MANAGER or ACCOUNT_MANAGER
        return <Navigate to="/crm/home" replace />;
    }

    return <Outlet />;
};
