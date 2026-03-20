import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
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

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-background flex items-center justify-center p-8">
          <div className="bg-card border border-border rounded-lg p-8 max-w-lg w-full">
            <h2 className="text-lg font-semibold text-severity-critical mb-2">Application Error</h2>
            <p className="text-sm text-text-secondary mb-4">
              An unexpected error occurred. Try refreshing the page.
            </p>
            <pre className="text-xs bg-elevated p-3 rounded border border-border overflow-auto text-text-muted max-h-40">
              {this.state.error?.message}
            </pre>
            <button
              onClick={() => window.location.reload()}
              className="mt-4 bg-accent hover:bg-accent-hover text-white text-sm px-4 py-2 rounded-md transition-colors"
            >
              Reload
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
