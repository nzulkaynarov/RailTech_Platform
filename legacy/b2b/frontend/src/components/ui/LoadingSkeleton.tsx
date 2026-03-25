import React from 'react';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

// Re-export shadcn Skeleton as the base building block so existing
// `import { Skeleton } from '@/components/ui/LoadingSkeleton'` keeps working.
export { Skeleton };

/** Skeleton for a KPI card. */
export const KPICardSkeleton: React.FC = () => (
  <div className="p-4 rounded-xl border border-border bg-white dark:bg-background space-y-3">
    <Skeleton className="h-3 w-24" />
    <Skeleton className="h-7 w-32" />
    <Skeleton className="h-3 w-16" />
  </div>
);

/** Skeleton for a table row. */
export const TableRowSkeleton: React.FC<{ columns?: number }> = ({ columns = 5 }) => (
  <tr className="border-b border-border dark:border-border">
    {Array.from({ length: columns }).map((_, i) => (
      <td key={i} className="py-3 px-3">
        <Skeleton className={cn('h-4', i === 0 ? 'w-40' : 'w-20')} />
      </td>
    ))}
  </tr>
);

/** Skeleton for a list of table rows. */
export const TableSkeleton: React.FC<{ rows?: number; columns?: number }> = ({
  rows = 5,
  columns = 5,
}) => (
  <tbody>
    {Array.from({ length: rows }).map((_, i) => (
      <TableRowSkeleton key={i} columns={columns} />
    ))}
  </tbody>
);

/** Skeleton for a product card in catalog grid — matches ProductCard structure. */
export const ProductCardSkeleton: React.FC = () => (
  <div className="rounded-xl border border-border bg-white dark:bg-background overflow-hidden">
    {/* Image area — aspect-[4/3] same as ProductCard */}
    <Skeleton className="aspect-[4/3] w-full rounded-none" />
    {/* Body */}
    <div className="p-4 space-y-2.5">
      <div className="flex justify-between">
        <Skeleton className="h-3 w-16" />
        <Skeleton className="h-3 w-12" />
      </div>
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-3/4" />
      <Skeleton className="h-3 w-1/2" />
      <div className="flex justify-between items-center pt-1 border-t border-border dark:border-border">
        <div className="space-y-1.5">
          <Skeleton className="h-2.5 w-14" />
          <Skeleton className="h-5 w-24" />
        </div>
        <Skeleton className="h-9 w-9 rounded-lg" />
      </div>
    </div>
  </div>
);

/** Grid of product card skeletons. */
export const CatalogGridSkeleton: React.FC<{ count?: number }> = ({ count = 8 }) => (
  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
    {Array.from({ length: count }).map((_, i) => (
      <ProductCardSkeleton key={i} />
    ))}
  </div>
);
