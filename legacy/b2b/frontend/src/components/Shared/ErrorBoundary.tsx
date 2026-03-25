import { Component, ErrorInfo, ReactNode } from 'react';
import i18n from 'i18next';
import { AlertTriangle, RefreshCw, Home } from 'lucide-react';
import { Button } from '@/components/ui/button';

interface Props {
  children?: ReactNode;
}

interface State {
  hasError: boolean;
  error?: Error;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Uncaught error:', error, errorInfo);
  }

  public render() {
    if (this.state.hasError) {
      const t = (key: string) => i18n.t(key);

      return (
        <div className="min-h-screen flex items-center justify-center p-6 bg-background">
          <div className="max-w-md w-full bg-card rounded-[40px] p-10 shadow-2xl border border-border text-center space-y-8 animate-in fade-in zoom-in-95 duration-500">
            <div className="w-20 h-20 bg-destructive/10 rounded-3xl flex items-center justify-center mx-auto mb-6">
              <AlertTriangle className="w-10 h-10 text-destructive" />
            </div>

            <div className="space-y-2">
              <h1 className="text-2xl font-black text-foreground uppercase tracking-tight">{t('error.title')}</h1>
              <p className="text-muted-foreground font-medium whitespace-pre-wrap break-words">
                {this.state.error?.message || t('error.defaultMessage')}
              </p>
            </div>

            <div className="flex flex-col gap-3">
              <Button
                onClick={() => window.location.reload()}
                variant="destructive"
                className="w-full py-4 h-auto font-black rounded-2xl shadow-lg active:scale-95 uppercase tracking-widest text-xs"
              >
                <RefreshCw className="w-4 h-4" /> {t('error.hardRefresh')}
              </Button>
              <Button
                onClick={() => window.location.href = '/'}
                variant="secondary"
                className="w-full py-4 h-auto font-black rounded-2xl active:scale-95 uppercase tracking-widest text-xs"
              >
                <Home className="w-4 h-4" /> {t('error.returnHome')}
              </Button>
            </div>

            <div className="pt-4">
              <p className="text-xs font-black uppercase tracking-[0.2em] text-muted-foreground opacity-50">{t('error.supportId')}: ERR_UI_CRASH</p>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
