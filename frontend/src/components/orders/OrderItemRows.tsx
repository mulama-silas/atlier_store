import React from 'react';
import { useStore } from '../../context/StoreContext';
import { useRouter } from '../../router/RouterContext';
import { Order } from '../../types';
import { formatPrice } from '../../utils/currency';
import { OrderItemThumb } from './OrderItemThumb';

interface OrderItemRowsProps {
  order: Order;
  showTrackAction?: boolean;
  showReviewAction?: boolean;
  showSubtotal?: boolean;
}

/** Compact, responsive order item rows shared by customer order screens. */
export const OrderItemRows: React.FC<OrderItemRowsProps> = ({
  order,
  showTrackAction = true,
  showReviewAction = true,
  showSubtotal = false,
}) => {
  const { navigate } = useRouter();
  const { getProductById } = useStore();
  const canReview = order.status === 'delivered' || order.status === 'received';

  return (
    <>
      <ul className="divide-y divide-[#EEEAE3]" aria-label={`Items in order ${order.orderNumber}`}>
        {order.items.map((item) => {
          const product = getProductById(item.productId);
          const reviewPath = `/product/${encodeURIComponent(product?.slug || item.productId)}#product-reviews`;

          return (
            <li key={item.id} className="flex min-w-0 items-center gap-3 py-3.5 sm:gap-4">
              <OrderItemThumb item={item} className="h-12 w-12 shrink-0 rounded-lg border border-[#E8E5DF] sm:h-14 sm:w-14" />
              <div className="min-w-0 flex-1">
                <h3 className="line-clamp-2 break-words text-xs font-semibold leading-5 text-[#181716] sm:text-sm">
                  {item.productName}
                </h3>
                <p className="mt-0.5 break-words text-[10px] leading-4 text-[#827E77] sm:text-[11px]">
                  {item.variantDetails ? `${item.variantDetails}  ·  ` : ''}Qty: {item.quantity}
                </p>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {showTrackAction && order.status !== 'cancelled' && (
                    <button
                      type="button"
                      onClick={() => navigate(`/track?order=${encodeURIComponent(order.orderNumber)}`)}
                      className="rounded border border-[#D8D3CB] bg-white px-2 py-0.5 text-[10px] leading-4 text-[#3C3934] transition-colors hover:border-[#A2574F] hover:text-[#83443D] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F]"
                    >
                      Track
                    </button>
                  )}
                  {showReviewAction && canReview && (
                    <button
                      type="button"
                      onClick={() => navigate(reviewPath)}
                      className="rounded border border-[#D8D3CB] bg-white px-2 py-0.5 text-[10px] leading-4 text-[#3C3934] transition-colors hover:border-[#A2574F] hover:text-[#83443D] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#A2574F]"
                    >
                      Write a review
                    </button>
                  )}
                </div>
              </div>
              <span className="max-w-[6rem] shrink-0 break-words text-right text-xs font-semibold text-[#181716] sm:text-sm">
                {formatPrice(item.subtotal)}
              </span>
            </li>
          );
        })}
      </ul>
      {showSubtotal && (
        <div className="flex items-center justify-between gap-4 border-t border-[#EEEAE3] pt-3 text-xs text-[#63605A]">
          <span>Subtotal</span>
          <span className="font-semibold text-[#181716]">{formatPrice(order.subtotal)}</span>
        </div>
      )}
    </>
  );
};
