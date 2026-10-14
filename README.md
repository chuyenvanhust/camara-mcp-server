# MCP server cho Open Gateway

Gói Python độc lập cung cấp MCP 2026-07-28, tools/prompts/resources, OAuth truy cập MCP và adapter SIM Swap live. Không cần mcp-client. Bridge chạy trên máy host của khách hàng.

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

## Đặt sau gateway

Để chạy thử container local trên cổng 3001, dùng `docker compose -f compose.local.yaml up -d --build` từ thư mục server. Container dùng credential trong .env, mount key read-only và giữ cổng 3000 cho server Python đang chạy. Xem log bằng `docker compose -f compose.local.yaml logs -f server`; dừng bằng `docker compose -f compose.local.yaml down`. Khi thử host với container, đặt ba URL MCP của client thành http://localhost:3001/mcp, http://localhost:3001 và http://localhost:3001/oauth/token, rồi khởi động lại host. Có thể dùng environment override thay vì sửa .env để thử tạm.

Triển khai cả thư mục này (source + manifest + dependency), không chỉ sim_swap.py. Không đóng gói .env, keys hoặc .venv vào image; cấp secrets/khóa bằng môi trường hoặc volume được bảo vệ. Dùng .env.gateway.example làm mẫu cấu hình HTTPS công khai. BIND_HOST và PORT là địa chỉ nội bộ; MCP_SERVER_URL và MCP_ISSUER là danh tính công khai. Không còn bắt URL công khai phải trùng port nội bộ.

Dockerfile là mẫu chạy Linux bằng user không phải root. Build từ thư mục này, publish port 3000 sau HTTPS gateway. Mount key tại /run/secrets/upstream-private.pem và đặt UPSTREAM_PRIVATE_KEY_PATH tương ứng. Chưa kiểm thử build Docker hoặc nền tảng Open Gateway thực tế.

Bộ manifest và các lệnh build/push/deploy, tạo Secret/TLS, cấu hình bridge và đọc log Kubernetes nằm trong [k8s/README.md](k8s/README.md). Dockerfile dùng hai stage, runtime chạy UID/GID 10001; không chứa credential trong image.

Giữ đường dẫn công khai /mcp; chưa hỗ trợ tự cấu hình prefix khác. Gateway chuyển tiếp Host công khai, Authorization, Content-Type, Accept và header MCP; không redirect endpoint MCP/token. Route cả discovery:

- /mcp
- /.well-known/oauth-protected-resource/mcp
- /.well-known/oauth-protected-resource
- /.well-known/oauth-authorization-server
- /oauth/token nếu dùng OAuth tích hợp hiện tại

SDK và middleware kiểm tra Host/Origin theo cấu hình công khai. MCP_ALLOWED_ORIGINS là danh sách origin chính xác, phân cách dấu phẩy. Không tin tùy ý X-Forwarded-Host. Reverse proxy cần timeout đủ cho API upstream và hỗ trợ Streamable HTTP/SSE nếu sử dụng streaming.

OAuth tích hợp hiện tại hỗ trợ một client, client_secret_basic và token HS256. Nó phù hợp thử nghiệm một khách hàng; trước khi phục vụ nhiều ngân hàng cần quản lý nhiều client/phân quyền và tích hợp authorization server của nền tảng. Không chỉ thay MCP_TOKEN_URL sang issuer ngoài: phải thay cả discovery và verifier. Cấu hình remote hiện hỗ trợ issuer cùng hệ thống tích hợp; chưa có verifier JWKS của gateway ngoài.

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

JWT Viettel: iss=sub=client ID, aud=token endpoint, exp=iat+120, nbf=iat-120, jti UUID, kid đăng ký. Form token có grant_type, scope, client_assertion_type, client_assertion; không client_id. Scope upstream sim-swap sim-swap:check độc lập scope MCP gateway:invoke.

## Xác minh

Trước khi tách gói: đã kiểm thử live Viettel qua SDK client mô phỏng host. Chưa xác minh UI Claude Desktop thật. Không sao chép .venv Windows sang Linux; cài lại từ lock. Các regression được giữ ngoài gói vận hành.

Sau khi tách gói: 15 ca regression đã đạt; smoke test SDK host → client STDIO → server HTTP/OAuth đọc tools/prompts/resources và chặn input sai trước upstream. Đã kiểm tra cấu hình HTTPS công khai qua ASGI test transport và mỗi môi trường không import được package bên kia. Không gọi lại Viettel trong lần kiểm thử tách gói này.

## Xem log

Log JSON ghi vào stderr và mặc định `logs/server.log`, tối đa 5 MB/file, giữ 3 bản xoay vòng. Khởi động lại tiến trình sau khi cập nhật code.

```powershell
Get-Content C:\camara-mcp\mcp-server\logs\server.log -Tail 50 -Wait
```

Cấu hình riêng trong .env: LOG_LEVEL=INFO, LOG_TO_FILE=true. Có thể đặt LOG_FILE bằng đường dẫn riêng; đường dẫn tương đối được tính từ thư mục gói. LOG_TO_FILE=false để chỉ ghi stderr. Log dùng timestamp UTC. Không ghi body, số điện thoại, token, assertion hoặc key.

Các dòng start/end ghi duration_ms, outcome, mã lỗi/status nếu có. Server ghi tool.call, upstream.token (cache_hit/lock_wait_ms), upstream.oauth, upstream.api (attempt/correlator), http.request (MCP/OAuth/discovery). Bridge ghi oauth.discovery, oauth.token, bridge.connected và mcp.request. call_id nối các chặng trong cùng tiến trình; correlator từ kết quả API hỗ trợ đối chiếu server/bridge. Health probe không tạo log mỗi lần. Bridge không ghi log lên stdout.
