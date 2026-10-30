---
id: auth-session
name: Xác thực và phiên đăng nhập
description: Tự tạo phiên trong kịch bản, dùng email duy nhất, kiểm tra hết phiên sau đăng xuất.
version: 1.0
agents: [writer, reviewer, explorer]
triggers: [đăng nhập, đăng ký, đăng xuất, tài khoản, mật khẩu, phiên, login, logout, register, signup, auth, session, password, checkout, đặt hàng, thanh toán]
---
- Each case starts logged out. If an endpoint needs a user, register {{$email}} with a password of at least 8 characters inside the same case, then call it.
- Never reuse a fixed email for registration: it fails with 409 on the second run. Use {{$email}}.
- A successful-login case registers the account first, then logs out, then logs in with the same credentials.
- Test: wrong password, unknown email, access without login, access after logout.
- Do not put real credentials in a test. Use {{username}} and {{password}} when a test account is provided.
