import React from 'react';
import { Product } from '../../../api/catalogApi';
import { ProductCard } from './ProductCard';
import { GridDensity } from '../PublicCatalog';

interface CatalogGridProps {
    products: Product[];
    onProductClick: (product: Product) => void;
    canSeePrices: boolean;
    density?: GridDensity;
}

const densityClasses: Record<GridDensity, string> = {
    comfortable: 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-2 xl:grid-cols-3 gap-6',
    normal:      'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4',
    compact:     'grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3',
};

export const CatalogGrid: React.FC<CatalogGridProps> = ({ products, onProductClick, canSeePrices, density = 'normal' }) => {
    return (
        <div className={`grid ${densityClasses[density]}`}>
            {products.map(product => (
                <ProductCard
                    key={product.id}
                    product={product}
                    onClick={onProductClick}
                    canSeePrices={canSeePrices}
                />
            ))}
        </div>
    );
};
