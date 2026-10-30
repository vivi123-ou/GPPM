---
id: ui-locators
name: Chiến lược locator và kịch bản UI
description: Thứ tự ưu tiên locator ổn định, kịch bản có kiểm chứng kết quả nhìn thấy được.
version: 1.0
agents: [writer, explorer, reviewer]
triggers: [giao diện, trang, nút, màn hình, ui, page, button, form, click, trình duyệt, browser]
---
- Locator order: testid, then role + accessible name, then label or placeholder for inputs, then visible text, and css only as a last resort.
- Copy testid, role and name exactly from the element list. Never invent an element that is not listed.
- Avoid css with position (nth-child), generated classes or long paths: they break on the next release.
- Start with goto. After each important action verify the visible result (cart count, total, message, new page).
- App messages appear in elements marked role "status" or with an id or class containing error or message: target them with css "#id".
- Required empty fields are blocked by the browser, so the app shows no message: do not assert an app message for them.
- Assert text that the page really shows, not text you assume it shows.
