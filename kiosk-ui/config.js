// Runtime config for the kiosk UI. Edit this file directly on the Pi if
// values change (backend port, cart_id) -- no build step, no rebuild
// needed, since this whole UI is plain static files served as-is.
window.SMARTCART_CONFIG = {
  apiBaseUrl: "http://localhost:8000", // backend runs on the same Pi 4 (single-box architecture)
  cartId: "cart-01",
  cartSummaryPollMs: 2000, // how often the shopping screen re-fetches the live cart
  recommendationsPollMs: 8000, // recommendations change slower than the cart itself -- polled less often
};
