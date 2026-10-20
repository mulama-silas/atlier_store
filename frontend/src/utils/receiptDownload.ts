import { api } from '../services/apiClient';
import type { OrderStatus } from '../types';

const RECEIPT_READY_STATUSES: OrderStatus[] = [
  'confirmed',
  'processing',
  'shipped',
  'delivered',
  'received',
];

export function isReceiptAvailableForOrder(status: OrderStatus): boolean {
  return RECEIPT_READY_STATUSES.includes(status);
}

export async function downloadOrderReceipt(orderNumber: string): Promise<void> {
  const receipt = await api.getOrderReceipt(orderNumber);
  if (receipt.status !== 'generated') {
    throw new Error('The receipt is not available yet.');
  }

  const blob = await api.downloadReceipt(receipt.receiptNumber);
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `${receipt.receiptNumber}.pdf`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
