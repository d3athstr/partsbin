// Known vendors, mirrors the backend ORDER_VENDORS list. Used for the
// component "where to buy" vendor dropdown.
export const VENDORS = ['amazon', 'aliexpress', 'adafruit', 'mouser', 'digikey',
                        'seeed', 'rokland', 'jlcpcb', 'pololu', 'other'];

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
