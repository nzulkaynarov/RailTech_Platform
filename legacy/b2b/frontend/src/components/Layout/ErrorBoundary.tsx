import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import { AlertTriangle, RefreshCw, Home } from 'lucide-react';
import i18n from 'i18next';
import { Button } from '@/components/ui/button';

interface Props {
    children: ReactNode;
    fallback?: ReactNode;
}

interface State {
    hasError: boolean;
    error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
    state: State = { hasError: false, error: null };

    static getDerivedStateFromError(error: Error): State {
        return { hasError: true, error };
    }

    componentDidCatch(error: Error, info: ErrorInfo) {
        console.error('[ErrorBoundary]', error, info.componentStack);
    }

    handleReload = () => {
        window.location.reload();
    };

    handleGoHome = () => {
        window.location.href = '/';
    };

    render() {
        if (this.state.hasError) {
            if (this.props.fallback) return this.props.fallback;

            const t = i18n.t.bind(i18n);

            return (
                <div className="flex h-screen items-center justify-center bg-muted p-6">
                    <div className="max-w-md w-full bg-card border border-border rounded-xl p-8 shadow-lg text-center space-y-4">
                        <div className="w-12 h-12 mx-auto rounded-full bg-destructive/10 flex items-center justify-center">
                            <AlertTriangle className="w-6 h-6 text-destructive" />
                        </div>
                        <h2 className="text-lg font-bold text-foreground">
                            {t('error.title')}
                        </h2>
                        <p className="text-sm text-muted-foreground">
                            {t('error.description')}
                        </p>
                        {this.state.error && (
                            <pre className="text-xs text-left bg-muted p-3 rounded-lg overflow-auto max-h-32 text-destructive">
                                {this.state.error.message}
                            </pre>
                        )}
                        <div className="flex gap-3 justify-center pt-2">
                            <Button
                                variant="outline"
                                onClick={this.handleGoHome}
                            >
                                <Home className="w-4 h-4" />
                                {t('error.goHome')}
                            </Button>
                            <Button
                                onClick={this.handleReload}
                            >
                                <RefreshCw className="w-4 h-4" />
                                {t('error.reload')}
                            </Button>
                        </div>
                    </div>
                </div>
            );
        }

        return this.props.children;
    }
}
