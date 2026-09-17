// Known vendors, mirrors the backend ORDER_VENDORS list. Used for the
// component "where to buy" vendor dropdown.
export const VENDORS = ['amazon', 'aliexpress', 'adafruit', 'mouser', 'digikey',
                        'seeed', 'rokland', 'jlcpcb', 'pololu', 'ebay', 'polycase',
                        'onlinemetals', 'yakima', 'other'];

/**
 * Short human label for a component's vendor purchase reference, e.g.
 * "Adafruit #258", "Mouser", or "" when nothing useful is set.
 */
export const productRefLabel = (vendor, sku) => {
  const v = vendor ? vendor.charAt(0).toUpperCase() + vendor.slice(1) : '';
  if (v && sku) return `${v} #${sku}`;
  if (v) return v;
  if (sku) return `#${sku}`;
  return '';
};

/**
 * Deep link to the vendor's order-details page (login-gated by the vendor).
 * Only vendors with stable URL patterns; others return null and render as text.
 *
 * eBay is deliberately absent. Its orders reach us via forwarded PayPal
 * receipts, so order_no is a PayPal checkout id (a UUID like
 * "c4bda27b-f77b-4201-ad5c-31f0bb7810ff"), NOT an eBay order number
 * ("12-13456-78901"). Any /vod/FetchOrderDetails link built from it would
 * 404. Leave it as text unless a real eBay order number ever gets stored.
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
