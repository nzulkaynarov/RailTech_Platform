export function LoadingSkeleton() {
  return (
    <div className="flex items-center justify-center min-h-screen bg-background">
      <div className="space-y-4">
        <div className="h-8 bg-muted rounded animate-pulse w-48"></div>
        <div className="space-y-2">
          <div className="h-4 bg-muted rounded animate-pulse w-64"></div>
          <div className="h-4 bg-muted rounded animate-pulse w-56"></div>
        </div>
      </div>
    </div>
  );
}
