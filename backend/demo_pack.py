"""Bộ kịch bản mẫu cho Demo Shop, viết sẵn và không cần AI.

Dùng khi trình diễn mà mạng hoặc hạn mức AI gặp sự cố, và làm mốc so sánh cho phép đo phát hiện lỗi.
Giao diện ghi rõ đây là bộ mẫu, không phải kết quả do AI sinh.
"""
from backend.models import TestCase

REQUIREMENT = """Khách hàng đặt mua điện thoại tại TVT MOBILE.
- Đặt hàng yêu cầu đăng nhập; chưa đăng nhập gọi đặt hàng trả về 401.
- Đặt hàng hợp lệ trả về 201; tổng tiền (total) bằng tổng (đơn giá × số lượng) của các sản phẩm.
- Email không hợp lệ (rỗng, thiếu @, thiếu tên miền) bị từ chối với mã 422.
- Số lượng mỗi sản phẩm từ 1 đến 20; ngoài khoảng này bị từ chối với mã 422.
- Sản phẩm không tồn tại trả về 404. Đặt vượt số lượng tồn kho trả về 409.
- Tra cứu đơn hàng theo mã đơn trả về đúng thông tin đơn."""

_REGISTER = {"method": "POST", "path": "/api/shop/auth/register",
             "body": {"name": "Khách TestPilot", "email": "{{$email}}", "password": "TestPilot#2026"},
             "expect": {"status": 201}}


def _order(items, email="khach@example.com"):
    return {"customer_name": "Nguyễn Minh Anh", "email": email, "address": "12 Nguyễn Huệ, Quận 1", "items": items}


_ITEM = [{"product_id": "iphone-15", "quantity": 1}]

_FUNCTIONAL = [
    dict(title="Đặt một sản phẩm: tổng tiền bằng đơn giá nhân số lượng", priority="high", technique="happy",
         covers=["Đặt hàng hợp lệ trả về 201; tổng tiền bằng tổng (đơn giá × số lượng)"], steps=[
             _REGISTER,
             {"method": "POST", "path": "/api/shop/checkout",
              "body": _order([{"product_id": "iphone-15", "quantity": 2}]),
              "expect": {"status": 201, "json_contains": {"total": 39980000}}}]),
    dict(title="Đặt nhiều sản phẩm: tổng tiền cộng đúng các dòng", priority="high", technique="business",
         covers=["Đặt hàng hợp lệ trả về 201; tổng tiền bằng tổng (đơn giá × số lượng)"], steps=[
             _REGISTER,
             {"method": "POST", "path": "/api/shop/checkout",
              "body": _order([{"product_id": "iphone-15", "quantity": 1}, {"product_id": "pixel-8", "quantity": 2}]),
              "expect": {"status": 201, "json_contains": {"total": 49970000}}}]),
    dict(title="Đặt hàng khi chưa đăng nhập bị từ chối", priority="high", technique="negative",
         covers=["Đặt hàng yêu cầu đăng nhập; chưa đăng nhập gọi đặt hàng trả về 401"], steps=[
             {"method": "POST", "path": "/api/shop/checkout", "body": _order(_ITEM), "expect": {"status": 401}}]),
    dict(title="Email sai định dạng bị từ chối", priority="high", technique="negative",
         covers=["Email không hợp lệ (rỗng, thiếu @, thiếu tên miền) bị từ chối với mã 422"],
         data_sets=[{"name": "thieu_a_cong", "values": {"bad_email": "khach.example.com"}, "expected": "reject"},
                    {"name": "thieu_ten_mien", "values": {"bad_email": "khach@example"}, "expected": "reject"}],
         steps=[_REGISTER, {"method": "POST", "path": "/api/shop/checkout", "body": _order(_ITEM, "{{bad_email}}"),
                            "expect": {"status": 422}}]),
    dict(title="Số lượng ngoài khoảng 1 đến 20 bị từ chối", priority="medium", technique="boundary",
         covers=["Số lượng mỗi sản phẩm từ 1 đến 20; ngoài khoảng này bị từ chối với mã 422"],
         data_sets=[{"name": "duoi_bien_0", "values": {"qty": 0}, "expected": "reject"},
                    {"name": "tren_bien_21", "values": {"qty": 21}, "expected": "reject"}],
         steps=[_REGISTER, {"method": "POST", "path": "/api/shop/checkout",
                            "body": _order([{"product_id": "iphone-15", "quantity": "{{qty}}"}]),
                            "expect": {"status": 422}}]),
    dict(title="Đặt đúng bằng tồn kho được chấp nhận", priority="medium", technique="boundary",
         covers=["Đặt vượt số lượng tồn kho trả về 409"], steps=[
             _REGISTER,
             {"method": "POST", "path": "/api/shop/checkout",
              "body": _order([{"product_id": "pixel-8", "quantity": 9}]),
              "expect": {"status": 201, "json_contains": {"total": 134910000}}}]),
    dict(title="Đặt vượt tồn kho trả về 409", priority="high", technique="business",
         covers=["Đặt vượt số lượng tồn kho trả về 409"], steps=[
             _REGISTER,
             {"method": "POST", "path": "/api/shop/checkout",
              "body": _order([{"product_id": "pixel-8", "quantity": 10}]), "expect": {"status": 409}}]),
    dict(title="Sản phẩm không tồn tại trả về 404", priority="medium", technique="negative",
         covers=["Sản phẩm không tồn tại trả về 404"], steps=[
             _REGISTER,
             {"method": "POST", "path": "/api/shop/checkout",
              "body": _order([{"product_id": "khong-ton-tai", "quantity": 1}]), "expect": {"status": 404}}]),
    dict(title="Tra cứu đơn vừa đặt trả về đúng tổng tiền", priority="high", technique="state",
         covers=["Tra cứu đơn hàng theo mã đơn trả về đúng thông tin đơn"], steps=[
             _REGISTER,
             {"method": "POST", "path": "/api/shop/checkout", "body": _order(_ITEM), "expect": {"status": 201},
              "save": {"order_id": "order_id"}},
             {"method": "GET", "path": "/api/shop/orders/{{order_id}}",
              "expect": {"status": 200, "json_contains": {"total": 19990000, "email": "khach@example.com"}}}]),
]

_T = lambda testid: {"testid": testid}

_UI = [
    dict(title="Thêm vào giỏ: số lượng và tổng tiền cập nhật", priority="high", technique="happy", steps=[
        {"action": "goto", "url": "/shop"},
        {"action": "click", "target": _T("add-iphone-15")},
        {"action": "click", "target": _T("add-pixel-8")},
        {"action": "assert_text", "target": {"css": "#count"}, "expect": "2"},
        {"action": "assert_text", "target": {"css": "#total"}, "expect": "34.980.000"}]),
    dict(title="Đăng nhập sai mật khẩu hiển thị thông báo lỗi", priority="high", technique="negative", steps=[
        {"action": "goto", "url": "/shop/login"},
        {"action": "fill", "target": _T("login-email"), "value": "khong-ton-tai@example.com"},
        {"action": "fill", "target": _T("login-password"), "value": "sai-mat-khau-demo"},
        {"action": "click", "target": {"role": "button", "name": "Đăng nhập"}},
        {"action": "assert_text", "target": {"css": "#auth-error"}, "expect": "Email hoặc mật khẩu chưa đúng"}]),
    dict(title="Luồng mua hàng: đăng ký, chọn máy, đặt hàng thành công", priority="high", technique="journey", steps=[
        {"action": "goto", "url": "/shop/register"},
        {"action": "fill", "target": _T("register-name"), "value": "Khách TestPilot"},
        {"action": "fill", "target": _T("register-email"), "value": "{{$email}}"},
        {"action": "fill", "target": _T("register-password"), "value": "TestPilot#2026"},
        {"action": "fill", "target": _T("register-password-confirmation"), "value": "TestPilot#2026"},
        {"action": "click", "target": {"role": "button", "name": "Tạo tài khoản"}},
        {"action": "click", "target": _T("add-iphone-15")},
        {"action": "fill", "target": _T("customer-name"), "value": "Khách TestPilot"},
        {"action": "click", "target": _T("checkout-button")},
        {"action": "click", "target": _T("confirm-order-button")},
        {"action": "assert_text", "target": {"css": "#message"}, "expect": "Đặt hàng thành công"}]),
]


def build_cases(prefix: str = "TC-DEMO") -> list[TestCase]:
    out = []
    for i, c in enumerate(_FUNCTIONAL, 1):
        out.append(TestCase(id=f"{prefix}-{i:02d}", type="api", category="functional", **c))
    for i, c in enumerate(_UI, 1):
        out.append(TestCase(id=f"{prefix}U-{i:02d}", type="ui", category="functional", **c))
    return out
