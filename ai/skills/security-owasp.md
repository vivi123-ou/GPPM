---
id: security-owasp
name: Kiểm thử bảo mật OWASP
description: Kiểm tra kiểm soát truy cập, đầu vào độc hại, cấu hình; chỉ chứng minh điểm yếu, không phá dữ liệu.
version: 1.0
agents: [security, reviewer]
---
Only for systems the user is authorised to test. Payloads prove a weakness and must not damage data or degrade service.
- A01 Broken access control: read another user's resource (IDOR): user A creates it, log out or use a new session, request it by ID; expect 401, 403 or 404. Call protected endpoints without logging in.
- A03 Injection: send SQL and script text in string fields; the system must answer with a normal status (below 500), expose no SQL or stack trace and not reflect the script into HTML.
- A04 Insecure design: client must not control prices or totals (mass assignment); wrong-order state changes are refused; zero or negative amounts are refused.
- A05 Misconfiguration: security headers present; errors reveal no framework internals.
- A07 Authentication failures: repeated wrong passwords must eventually be limited; session cookie is HttpOnly and SameSite.
Expected results use "status_in", "status_lt", "not_contains", "headers", "cookie_flags". Set category to "security" and technique to the OWASP item.
