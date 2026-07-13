/**
 * Deep link to the vendor's order-details page (login-gated by the vendor).
 * Only vendors with stable URL patterns; others return null and render as text.
 */
export const vendorOrderUrl = (vendor, orderNo) => {
  if (!orderNo) return null;
  switch (vendor) {
    case 'amazon':
      return `https://www.amazon.com/gp/css/order-details?orderID=${encodeURIComponent(orderNo)}`;
    case 'aliexpress':
      return `https://www.aliexpress.com/p/order/detail.html?orderId=${encodeURIComponent(orderNo)}`;
    default:
      return null;
  }
};
