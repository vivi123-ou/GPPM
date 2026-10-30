---
id: api-contract
name: Kiểm thử hợp đồng API
description: Dùng đúng status, trường và ràng buộc trong OpenAPI; đọc lại trạng thái sau khi ghi.
version: 1.0
agents: [writer, reviewer]
---
- Take the status codes from the API documentation. FastAPI validation errors are 422, not 400, unless the requirement says otherwise.
- A happy-path body must contain every required field with a value that satisfies its constraints.
- Verify response content, not only the status: at least one business field per successful call.
- After a write (POST/PUT/PATCH/DELETE), read the resource back in a later step to prove the change persisted.
- Capture generated IDs with "save" and reuse them; never hard-code IDs that the system generates.
- For list endpoints assert a known item with json_contains using a JSON array.
- Check negative paths per field: missing, empty, wrong type, out of range. One rule per case.
