import { db } from '../db/database';
import { ProductEntity, ProductVariantEntity } from '../db/types';
import { ProductDTO, ProductVariantDTO, PaginatedProductsResponse } from '../types/api';
import { ProductQueryInput, ProductCreateInput, ProductUpdateInput } from '../schemas/product.schema';
import { NotFoundError, AppError } from '../errors/app-error';
import { PricingService } from './pricing.service';

export class ProductService {
  /**
   * Queries products with pagination, filtering, and sorting.
   * Public storefront only receives ACTIVE products in active categories.
   */
  public static getProducts(query: ProductQueryInput): PaginatedProductsResponse {
    let allProducts = db.getAllProducts();

    // 1. Status Filter: Only ACTIVE products for public storefront
    allProducts = allProducts.filter((p) => p.status === 'ACTIVE');

    // 2. Active Category Check
    const activeCategoryIds = new Set(
      db
        .getAllCategories()
        .filter((c) => c.isActive)
        .map((c) => c.id)
    );
    allProducts = allProducts.filter((p) => activeCategoryIds.has(p.categoryId));

    // 3. Category Filter
    if (query.category && query.category !== 'all') {
      const targetCat = db.getCategoryBySlug(query.category) || db.getCategoryById(query.category);
      if (targetCat) {
        allProducts = allProducts.filter((p) => p.categoryId === targetCat.id);
      } else {
        // Unknown category slug yields empty result
        allProducts = [];
      }
    }

    // 4. Search Filter (by name or description or tagline)
    if (query.search) {
      const q = query.search.toLowerCase();
      allProducts = allProducts.filter(
        (p) =>
          p.name.toLowerCase().includes(q) ||
          p.description.toLowerCase().includes(q) ||
          p.tagline?.toLowerCase().includes(q)
      );
    }

    // 5. Sorting (Whitelisted options only)
    switch (query.sort) {
      case 'price_asc':
        allProducts.sort((a, b) => a.priceMinor - b.priceMinor);
        break;
      case 'price_desc':
        allProducts.sort((a, b) => b.priceMinor - a.priceMinor);
        break;
      case 'name':
        allProducts.sort((a, b) => a.name.localeCompare(b.name));
        break;
      case 'newest':
      default:
        allProducts.sort((a, b) => b.createdAt.getTime() - a.createdAt.getTime());
        break;
    }

    // 6. Controlled Pagination
    const total = allProducts.length;
    const page = Math.max(1, query.page);
    const limit = Math.min(100, Math.max(1, query.limit));
    const totalPages = Math.ceil(total / limit) || 1;
    const startIndex = (page - 1) * limit;
    const paginated = allProducts.slice(startIndex, startIndex + limit);

    const data: ProductDTO[] = paginated.map((p) => this.toDTO(p));

    return {
      data,
      pagination: {
        page,
        limit,
        total,
        totalPages,
      },
    };
  }

  /**
   * Retrieves a single product by ID or slug.
   */
  public static getProductByIdOrSlug(idOrSlug: string, isPublic = true): ProductDTO {
    const product = db.getProductById(idOrSlug) || db.getProductBySlug(idOrSlug);

    if (!product) {
      throw new NotFoundError('Product', idOrSlug);
    }

    if (isPublic) {
      if (product.status !== 'ACTIVE') {
        throw new NotFoundError('Product', idOrSlug);
      }
      const category = db.getCategoryById(product.categoryId);
      if (!category || !category.isActive) {
        throw new NotFoundError('Product', idOrSlug);
      }
    }

    return this.toDTO(product);
  }

  /**
   * Admin: Creates a product.
   */
  public static createProduct(input: ProductCreateInput): ProductDTO {
    const category = db.getCategoryById(input.categoryId) || db.getCategoryBySlug(input.categoryId);
    if (!category) {
      throw new AppError(400, 'CATEGORY_NOT_FOUND', `Category '${input.categoryId}' does not exist.`);
    }

    const id = `prod-${Date.now()}`;
    const product = db.insertProduct({
      id,
      name: input.name,
      slug: input.slug,
      tagline: input.tagline,
      description: input.description,
      details: input.details,
      priceMinor: PricingService.majorToMinor(input.price),
      compareAtPriceMinor: input.compareAtPrice !== undefined ? PricingService.majorToMinor(input.compareAtPrice) : undefined,
      categoryId: category.id,
      imageUrl: input.imageUrl,
      images: input.images || (input.imageUrl ? [input.imageUrl] : []),
      status: input.status ?? 'ACTIVE',
      isFeatured: input.isFeatured,
      isNewArrival: input.isNewArrival,
      isBestSeller: input.isBestSeller,
      createdAt: new Date(),
      updatedAt: new Date(),
    });

    return this.toDTO(product);
  }

  /**
   * Admin: Updates product.
   */
  public static updateProduct(id: string, input: ProductUpdateInput): ProductDTO {
    const updates: Partial<ProductEntity> = {};
    if (input.name !== undefined) updates.name = input.name;
    if (input.slug !== undefined) updates.slug = input.slug;
    if (input.tagline !== undefined) updates.tagline = input.tagline;
    if (input.description !== undefined) updates.description = input.description;
    if (input.details !== undefined) updates.details = input.details;
    if (input.price !== undefined) updates.priceMinor = PricingService.majorToMinor(input.price);
    if (input.compareAtPrice !== undefined) {
      updates.compareAtPriceMinor = PricingService.majorToMinor(input.compareAtPrice);
    }
    if (input.imageUrl !== undefined) updates.imageUrl = input.imageUrl;
    if (input.images !== undefined) updates.images = input.images;
    if (input.status !== undefined) updates.status = input.status;
    if (input.isFeatured !== undefined) updates.isFeatured = input.isFeatured;
    if (input.isNewArrival !== undefined) updates.isNewArrival = input.isNewArrival;
    if (input.isBestSeller !== undefined) updates.isBestSeller = input.isBestSeller;

    const updated = db.updateProduct(id, updates);
    return this.toDTO(updated);
  }

  /**
   * Admin: Archives product.
   */
  public static archiveProduct(id: string): ProductDTO {
    const updated = db.updateProduct(id, { status: 'ARCHIVED' });
    return this.toDTO(updated);
  }

  /**
   * Transforms entity to clean client-facing DTO with formatted major currency units.
   */
  public static toDTO(product: ProductEntity): ProductDTO {
    const category = db.getCategoryById(product.categoryId);
    const variants = db.getVariantsByProductId(product.id);

    const variantDTOs: ProductVariantDTO[] = variants.map((v) => {
      const authoritativePriceMinor = PricingService.getUnitPriceMinor(product, v);
      return {
        id: v.id,
        sku: v.sku,
        size: v.size,
        color: v.color,
        colorHex: v.colorHex,
        price: PricingService.minorToMajor(authoritativePriceMinor),
        stockQuantity: v.stockQuantity,
        isAvailable: v.isActive && v.stockQuantity > 0,
        isActive: v.isActive,
      };
    });

    return {
      id: product.id,
      name: product.name,
      slug: product.slug,
      tagline: product.tagline,
      description: product.description,
      details: product.details,
      price: PricingService.minorToMajor(product.priceMinor),
      compareAtPrice:
        product.compareAtPriceMinor !== undefined
          ? PricingService.minorToMajor(product.compareAtPriceMinor)
          : undefined,
      category: {
        id: category?.id || product.categoryId,
        name: category?.name || 'Collection',
        slug: category?.slug || 'all',
      },
      imageUrl: product.imageUrl,
      images: product.images,
      status: product.status,
      isFeatured: product.isFeatured,
      isNewArrival: product.isNewArrival,
      isBestSeller: product.isBestSeller,
      averageRating: product.averageRating,
      reviewCount: product.reviewCount || 0,
      variants: variantDTOs,
      createdAt: product.createdAt.toISOString(),
      updatedAt: product.updatedAt.toISOString(),
    };
  }
}
