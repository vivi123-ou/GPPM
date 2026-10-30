---
id: ecommerce-checkout
name: Nghiệp vụ thương mại điện tử
description: Giỏ hàng, tổng tiền, tồn kho, đơn hàng; các quy tắc nghiệp vụ dễ sai.
version: 1.0
agents: [writer, explorer, reviewer, security]
triggers: [giỏ, đặt hàng, thanh toán, đơn hàng, tồn kho, sản phẩm, tổng tiền, cart, checkout, order, stock, product, shop, total]
---
- Total equals the sum of unit price times quantity over all lines. Test with one line and with several lines, using real prices.
- Stock decreases by exactly the ordered quantity: read it before and after. A rejected order must not change stock.
- Ordering more than the stock is rejected; ordering exactly the stock is accepted.
- Unknown product, zero quantity and negative quantity are rejected.
- After ordering, looking up the order returns the same total and lines.
- UI journey: add product, cart count changes, total changes, fill details, confirm, success message shows order code.
