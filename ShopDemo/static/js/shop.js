let products = [];
let cart = {};
const money = value => new Intl.NumberFormat('vi-VN').format(value) + ' ₫';

async function load() {
  products = await (await fetch('/api/shop/products')).json();
  renderProducts();
  renderCart();
  const flags = await (await fetch('/api/shop/bugs')).json();
  if (flags.ui_v2) document.body.classList.add('v2');
}

function renderProducts() {
  document.querySelector('#products').innerHTML = products.map(product => `
    <article class="card">
      <div class="phone" style="--device-color:${product.color}">
        <span class="phone-placeholder" aria-hidden="true"></span>
        <img src="/shop-assets/images/${product.id}.jpg" alt="${product.name}"
             onload="this.previousElementSibling.style.display='none'"
             onerror="this.style.display='none'">
      </div>
      <div class="brandline">${product.brand}</div>
      <h3>${product.name}</h3>
      <div class="desc">${product.description}</div>
      <div class="buyline">
        <span class="price">${money(product.price)}</span>
        <button class="add" data-testid="add-${product.id}" onclick="add('${product.id}')">Thêm vào giỏ</button>
      </div>
      <div class="stock">Còn ${product.stock} sản phẩm</div>
    </article>`).join('');
}

function add(id) {
  cart[id] = (cart[id] || 0) + 1;
  renderCart();
}

function cartEntries() {
  return Object.entries(cart).filter(([, quantity]) => quantity > 0);
}

function cartTotal() {
  return cartEntries().reduce((sum, [id, quantity]) => {
    const product = products.find(item => item.id === id);
    return sum + product.price * quantity;
  }, 0);
}

function renderCart() {
  const entries = cartEntries();
  document.querySelector('#count').textContent = entries.reduce((sum, [, quantity]) => sum + quantity, 0);
  document.querySelector('#cart-items').innerHTML = entries.length
    ? entries.map(([id, quantity]) => {
        const product = products.find(item => item.id === id);
        return `<div class="cart-row"><span>${product.name} × ${quantity}</span><strong>${money(product.price * quantity)}</strong></div>`;
      }).join('')
    : '<div class="empty-cart">Giỏ hàng của bạn đang trống.</div>';
  document.querySelector('#total').textContent = money(cartTotal());
}

function getCheckoutData() {
  return {
    customer_name: document.querySelector('#customer').value.trim(),
    phone: document.querySelector('#phone').value.trim(),
    email: document.querySelector('#email').value.trim(),
    city: document.querySelector('#city').value.trim(),
    address: document.querySelector('#address').value.trim(),
    payment_method: document.querySelector('#payment-method').value,
    note: document.querySelector('#note').value.trim(),
    items: cartEntries().map(([product_id, quantity]) => ({ product_id, quantity }))
  };
}

function reviewOrder() {
  if (!cartEntries().length) {
    document.querySelector('#message').textContent = 'Hãy chọn sản phẩm trước khi đặt hàng.';
    return;
  }
  for (const id of ['customer', 'phone', 'email', 'city', 'address']) {
    const field = document.getElementById(id);
    if (!field.reportValidity()) return;
  }

  const data = getCheckoutData();
  const list = document.querySelector('#confirm-items');
  list.replaceChildren();
  for (const [id, quantity] of cartEntries()) {
    const product = products.find(item => item.id === id);
    const line = document.createElement('div');
    line.className = 'confirm-item';
    line.textContent = `${product.name} × ${quantity} — ${money(product.price * quantity)}`;
    list.appendChild(line);
  }

  const paymentLabel = data.payment_method === 'cod' ? 'Thanh toán khi nhận hàng (COD)' : 'Chuyển khoản ngân hàng';
  const details = [
    `Người nhận: ${data.customer_name}`,
    `Điện thoại: ${data.phone}`,
    `Email: ${data.email}`,
    `Địa chỉ: ${data.address}, ${data.city}`,
    `Thanh toán: ${paymentLabel}`,
    data.note ? `Ghi chú: ${data.note}` : ''
  ].filter(Boolean);
  document.querySelector('#confirm-customer').textContent = details.join(' · ');
  document.querySelector('#confirm-total').textContent = money(cartTotal());
  document.querySelector('#confirm-modal').hidden = false;
  document.body.classList.add('modal-open');
}

function closeConfirmation() {
  document.querySelector('#confirm-modal').hidden = true;
  document.body.classList.remove('modal-open');
}

async function confirmOrder() {
  const button = document.querySelector('.confirm-submit');
  button.disabled = true;
  button.textContent = 'Đang gửi đơn...';
  try {
    const response = await fetch('/api/shop/checkout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(getCheckoutData())
    });
    const result = await response.json();
    closeConfirmation();
    document.querySelector('#message').textContent = response.ok
      ? `Đặt hàng thành công! Mã đơn #${result.order_id} · ${money(result.total)}`
      : (result.detail || 'Đặt hàng thất bại. Hãy kiểm tra lại thông tin.');
    if (response.ok) {
      cart = {};
      await load();
    }
  } catch (error) {
    document.querySelector('#message').textContent = 'Không kết nối được máy chủ. Vui lòng thử lại.';
  } finally {
    button.disabled = false;
    button.textContent = 'Xác nhận đặt hàng';
  }
}

load();
