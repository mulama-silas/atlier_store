import { ProductDTO } from '../types/api';
import { Product, ProductVariant, CategorySlug, VariantSize } from '../types';

export function mapProductDtoToDomain(dto: ProductDTO): Product {
  return {
    id: dto.id,
    name: dto.name,
    slug: dto.slug,
    tagline: dto.tagline,
    description: dto.description,
    details: dto.details || [],
    price: dto.price,
    compareAtPrice: dto.compareAtPrice,
    categoryId: dto.category.id,
    categorySlug: (dto.category.slug || 'all') as CategorySlug,
    images: dto.images || [],
    status: (dto.status.toLowerCase() as 'active' | 'draft' | 'archived') || 'active',
    isFeatured: dto.isFeatured,
    isNewArrival: dto.isNewArrival,
    isBestSeller: dto.isBestSeller,
    createdAt: dto.createdAt,
    updatedAt: dto.updatedAt,
    variants: (dto.variants || []).map(
      (v): ProductVariant => ({
        id: v.id,
        productId: dto.id,
        size: (v.size || 'One Size') as VariantSize,
        color: v.color || '',
        colorHex: v.colorHex,
        sku: v.sku,
        price: v.price,
        stockQuantity: v.stockQuantity,
        isActive: v.isActive,
        isAvailable: v.isAvailable,
      })
    ),
    material: dto.material || '',
    careInstructions: dto.careInstructions || '',
    fitNotes: dto.fitNotes || '',
    modelSize: dto.modelSize || '',
    garmentMeasurements: dto.garmentMeasurements || {},
    averageRating: dto.averageRating,
    reviewCount: dto.reviewCount || 0,
  };
}
