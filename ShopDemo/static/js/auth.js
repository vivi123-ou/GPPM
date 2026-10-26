function postAuthError(message) {
  document.querySelector('#auth-error').textContent = message;
}

function destinationAfterAuth() {
  const next = new URLSearchParams(window.location.search).get('next');
  return next && next.startsWith('/shop') && !next.startsWith('//') ? next : '/shop';
}

const eyeClosed = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 3l18 18M10.6 10.6a2 2 0 0 0 2.8 2.8"/><path d="M9.9 5.2A11.2 11.2 0 0 1 12 5c5 0 8.7 3.5 10 7-.4 1.1-1.2 2.2-2.2 3.2M6.2 6.2C4.1 7.5 2.6 9.4 2 12c1.3 3.5 5 7 10 7 1.3 0 2.5-.3 3.6-.7"/></svg>';
const eyeOpen = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>';

document.querySelectorAll('.password-toggle').forEach(button => {
  const input = button.parentElement.querySelector('input');
  button.innerHTML = eyeClosed;
  button.addEventListener('click', () => {
    const showPassword = input.type === 'password';
    input.type = showPassword ? 'text' : 'password';
    button.innerHTML = showPassword ? eyeOpen : eyeClosed;
    button.setAttribute('aria-label', showPassword ? 'Ẩn mật khẩu' : 'Hiện mật khẩu');
    button.setAttribute('aria-pressed', String(showPassword));
  });
});

async function submitAuth(form, endpoint, payload) {
  const button = form.querySelector('button[type="submit"]');
  button.disabled = true;
  postAuthError('Đang xử lý...');
  try {
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || 'Không thể hoàn tất yêu cầu.');
    window.location.assign(destinationAfterAuth());
  } catch (error) {
    postAuthError(error.message || 'Không kết nối được máy chủ.');
    button.disabled = false;
  }
}

const loginForm = document.querySelector('#login-form');
if (loginForm) {
  loginForm.addEventListener('submit', event => {
    event.preventDefault();
    const form = new FormData(loginForm);
    submitAuth(loginForm, '/api/shop/auth/login', {
      email: form.get('email'), password: form.get('password')
    });
  });
}

const registerForm = document.querySelector('#register-form');
if (registerForm) {
  registerForm.addEventListener('submit', event => {
    event.preventDefault();
    const form = new FormData(registerForm);
    if (form.get('password') !== form.get('password_confirmation')) {
      postAuthError('Mật khẩu nhập lại chưa khớp.');
      return;
    }
    submitAuth(registerForm, '/api/shop/auth/register', {
      name: form.get('name'), email: form.get('email'), password: form.get('password')
    });
  });
}
