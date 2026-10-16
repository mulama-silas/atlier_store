from django.urls import path

from .views import (
    BackInStockView,
    CategoryDetailView,
    CategoryListView,
    ProductDetailView,
    ProductListView,
    ProductReviewsView,
)


urlpatterns = [
    path('products/', ProductListView.as_view(), name='product-list'),
    path('products/<str:identifier>', ProductDetailView.as_view(),
         name='product-detail-no-slash'),
    path('products/<str:identifier>/',
         ProductDetailView.as_view(), name='product-detail'),
    path('products/<str:identifier>/reviews',
         ProductReviewsView.as_view(), name='product-reviews-no-slash'),
    path('products/<str:identifier>/reviews/',
         ProductReviewsView.as_view(), name='product-reviews'),
    path('back-in-stock', BackInStockView.as_view(),
         name='back-in-stock'),
    path('back-in-stock/', BackInStockView.as_view(),
         name='back-in-stock-slash'),
    path('categories/', CategoryListView.as_view(), name='category-list'),
    path('categories/<slug:slug>', CategoryDetailView.as_view(),
         name='category-detail-no-slash'),
    path('categories/<slug:slug>/',
         CategoryDetailView.as_view(), name='category-detail'),
]
