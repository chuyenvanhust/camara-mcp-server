# MCP server cho Open Gateway

Gói Python độc lập cung cấp MCP 2026-07-28, tools/prompts/resources và adapter SIM Swap live; OAuth truy cập MCP do Open Gateway thực hiện. Không cần mcp-client. Bridge chạy trên máy host của khách hàng.

## Chạy local

```powershell
cd C:\camara-mcp\mcp-server
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.venv\Scripts\python.exe -m pip install -e . --no-deps
.venv\Scripts\python.exe scripts\setup.py
.venv\Scripts\python.exe server.py
```

.env và keys hiện có đã được chuyển nguyên dữ liệu cần thiết; key đã đăng ký không thay đổi. Setup giữ .env hiện có. Health: http://localhost:3000/health; MCP: http://localhost:3000/mcp.

## Đặt sau Open Gateway

Server không cấp hoặc xác thực token OAuth cho bridge. Endpoint /oauth/token và metadata OAuth local đã được bỏ. Bridge không còn tự xin token hoặc dùng MCP_CLIENT_SECRET. OAuth private_key_jwt để server gọi Viettel vẫn giữ nguyên.

Backend phải nằm sau Open Gateway có policy OAuth của nền tảng, không mở một route công khai đi vòng gateway. Manifest mặc định chỉ tạo Service ClusterIP; ingress.example.yaml là ví dụ routing, không được apply tự động. Cấu hình policy xác thực/quyền trên Open Gateway trước khi công bố /mcp. Host/Origin/body-limit vẫn được kiểm tra, nhưng không thay thế xác thực gateway.

MCP_SERVER_URL là URL MCP công khai; BIND_HOST/PORT là địa chỉ nội bộ. Nếu gateway đổi Host thành tên Service nội bộ, thêm đúng giá trị vào MCP_ALLOWED_HOSTS. Không tin tùy ý X-Forwarded-Host. Gateway thực hiện OAuth discovery/challenge nếu nền tảng yêu cầu; server không quảng bá authorization server giả.

Để thử local, chạy Python trên loopback hoặc dùng `docker compose -f compose.local.yaml up -d --build` trên cổng 3001. Không cần credential giữa client và server. Private key Viettel vẫn được mount read-only. Xem log bằng `docker compose -f compose.local.yaml logs -f server`.

Hướng dẫn triển khai: [k8s/README.md](k8s/README.md). Phần container phải rebuild sau thay đổi; không coi image cũ là đã bỏ OAuth local.

## Kiến trúc module

- camara_server/config.py: cấu hình riêng server.
- core/contracts.py, registry.py: hợp đồng, factory và catalog module.
- core/api_client.py: HTTP JSON, bearer, correlator; retry 401 một lần cùng body.
- auth/client_credentials.py: private_key_jwt hoặc client_secret_basic theo profile.
- auth/base.py: cache/lock token riêng mỗi profile.
- auth/signing.py: ký JWT RS256/PS256 bằng key server.
- modules/sim_swap.py: schema, rule ngữ nghĩa, tool, prompt và resource SIM Swap.

Thêm API bằng factory create_module(context) trả ApiModule, rồi khai báo module và auth profile trong gateway.toml. gateway.additional-api.toml.example cung cấp mẫu adapter tắt mặc định. Profile dùng env_prefix riêng; profile khác không phụ thuộc SIM Swap. Không có mock trong runtime.

## Rule xử lý SIM Swap

check_sim_swap gọi trực tiếp, nhận phoneNumber E.164 và maxAge theo giờ (1..2400; default 24 khi không nêu thời gian). Không ticket/phê duyệt bổ sung.

LLM đọc rule trong mô tả tool, cả hai prompt và resource policy trước khi xử lý: chỉ chuyển định dạng tương đương ngữ nghĩa. Được đổi 2 tuần thành 336 giờ; không đổi đầu số, đoán chữ số, thay thuê bao hay đổi cửa sổ để né lỗi. Mơ hồ thì hỏi làm rõ. Rule là hướng dẫn; schema không đối chiếu được câu người dùng gốc.

Prompts: fraud-check, sim-swap-natural-language. Resources: camara://sim-swap/contract, errors, policy. Host quyết định nạp prompt/resource.

Lỗi trả isError và structuredContent, giữ request/correlator/mã CAMARA. HTTP422 không chứng minh đầu số cũ hoặc thiếu maxAge. Upstream diagnostic là dữ liệu không tin cậy. swapped=false chỉ áp dụng đúng cửa sổ và định danh đã truy vấn, không phải kết luận gian lận.

JWT Viettel: iss=sub=client ID, aud=token endpoint, exp=iat+120, nbf=iat-120, jti UUID, kid đăng ký. Form token có grant_type, scope, client_assertion_type, client_assertion; không client_id. Scope upstream sim-swap sim-swap:check do nhà mạng cấp; policy truy cập MCP thuộc Open Gateway.

## Xác minh

Trước khi tách gói: đã kiểm thử live Viettel qua SDK client mô phỏng host. Chưa xác minh UI Claude Desktop thật. Không sao chép .venv Windows sang Linux; cài lại từ lock. Các regression được giữ ngoài gói vận hành.

Sau khi tách gói: 15 ca regression đã đạt; smoke test SDK host → client STDIO → server HTTP đọc tools/prompts/resources và chặn input sai trước upstream. Đã kiểm tra cấu hình HTTPS công khai qua ASGI test transport và mỗi môi trường không import được package bên kia. Không gọi lại Viettel trong lần kiểm thử tách gói này.

## Xem log

Log JSON ghi vào stderr và mặc định `logs/server.log`, tối đa 5 MB/file, giữ 3 bản xoay vòng. Khởi động lại tiến trình sau khi cập nhật code.

```powershell
Get-Content C:\camara-mcp\mcp-server\logs\server.log -Tail 50 -Wait
```

Cấu hình riêng trong .env: LOG_LEVEL=INFO, LOG_TO_FILE=true. Có thể đặt LOG_FILE bằng đường dẫn riêng; đường dẫn tương đối được tính từ thư mục gói. LOG_TO_FILE=false để chỉ ghi stderr. Log dùng timestamp UTC. Không ghi body, số điện thoại, token, assertion hoặc key.

Các dòng start/end ghi duration_ms, outcome, mã lỗi/status nếu có. Server ghi tool.call, upstream.token (cache_hit/lock_wait_ms), upstream.oauth, upstream.api (attempt/correlator), http.request (MCP/HTTP). Bridge ghi bridge.connected và mcp.request. call_id nối các chặng trong cùng tiến trình; correlator từ kết quả API hỗ trợ đối chiếu server/bridge. Health probe không tạo log mỗi lần. Bridge không ghi log lên stdout.

Phiên bản 0.6.0: đã bỏ OAuth local bridge/server. 21 ca hồi quy đã đạt; kiểm thử SDK host qua STDIO bridge tới server HTTP thành công với protocol hiện đại và legacy, không gọi Viettel. Chưa xác minh policy OAuth trên Open Gateway thực tế.
