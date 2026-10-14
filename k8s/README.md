# Docker / Kubernetes sau Open Gateway

Backend đã bỏ OAuth local. Open Gateway chịu trách nhiệm xác thực và quyền truy cập /mcp. OAuth/JWT để gọi Viettel vẫn nằm trong server. Bridge không chứa key hoặc OAuth client nhà mạng.

## Build và push

Từ C:\camara-mcp\mcp-server:

```powershell
docker build --platform linux/amd64 -t registry.example.com/camara/mcp-server:0.6.0 .
docker login registry.example.com
docker push registry.example.com/camara/mcp-server:0.6.0
```

Thay registry/tag trong lệnh và deployment.yaml. Dockerfile chạy UID/GID 10001, không đóng gói .env, keys hoặc venv Windows. Node ARM64 cần image kiến trúc tương ứng. Image cũ 0.5.0 còn OAuth local; cần rebuild phiên bản mới.

## Cấu hình và Secret

Sửa configmap.yaml: MCP_SERVER_URL là URL HTTPS công khai /mcp, còn BIND_HOST và PORT là backend nội bộ. Không cần MCP client/signing secret local. Nếu proxy rewrite Host, thêm MCP_ALLOWED_HOSTS gồm đúng tên Service và port được chuyển tới; giữ Origin allowlist cụ thể.

```powershell
kubectl config current-context
kubectl apply -f k8s/namespace.yaml
.venv\Scripts\python.exe scripts\prepare_k8s_credentials.py
kubectl -n camara-mcp create secret generic camara-mcp-credentials --from-env-file=k8s/credentials.env
kubectl -n camara-mcp create secret generic camara-mcp-upstream-key --from-file=upstream-private.pem=keys/upstream-private.pem
```

Lệnh create dùng cho lần đầu; Secret hiện có cần được cập nhật theo quy trình vận hành. credentials.env nay chỉ chứa UPSTREAM_CLIENT_ID và UPSTREAM_KEY_ID. Script không ghi đè file cũ; file được xuất trước phiên bản này nên được cập nhật riêng. Private key đã đăng ký được mount tại /run/secrets/upstream-private.pem, read-only, mode0440/fsGroup10001. Không thay key đã đăng ký. Secret/file cần RBAC, quyền file và encryption at rest phù hợp.

## Deploy backend và nối gateway

```powershell
kubectl kustomize k8s
kubectl apply --dry-run=server -k k8s
kubectl apply -k k8s
kubectl -n camara-mcp rollout status deployment/camara-mcp --timeout=180s
kubectl -n camara-mcp get pods,svc
```

Mặc định chỉ có Namespace, ConfigMap, Deployment và Service ClusterIP. Không tự tạo Ingress công khai. Đăng ký Service camara-mcp:80 làm backend trên Open Gateway; nền tảng công bố /mcp, thực hiện OAuth policy, TLS và các endpoint metadata/challenge tương ứng. Không cần route /oauth/token về server này. Không rewrite đường dẫn /mcp; giữ các header MCP và Authorization theo cơ chế gateway. Ingress.example.yaml chỉ là ví dụ routing, chỉ sử dụng sau khi gắn policy xác thực của nền tảng. Nếu registry cần pull credential, thêm imagePullSecrets.

Không mở backend đi vòng gateway. Chặn truy cập backend theo mạng/quyền của nền tảng; Service ClusterIP không tự giới hạn quyền giữa các Pod. Bộ mã này không biết cấu hình OAuth cụ thể của Open Gateway và chưa tự tạo policy xác thực trên nền tảng.

Probe /health có Host localhost:3000; chỉ kiểm tra tiến trình và module, không gọi Viettel. Container filesystem chỉ đọc, /tmp riêng; không mount service account token. Cluster cần egress tới token endpoint và SIM Swap API Viettel, theo IP allowlist/proxy/CA được onboard.

## Client và log

Client local chỉ cần MCP_SERVER_URL=http://localhost:3000/mcp. Qua gateway dùng:

```dotenv
MCP_SERVER_URL=https://mcp.example.vn/mcp
MCP_ACCESS_TOKEN_PATH=C:/protected/open-gateway-token.txt
```

Token file tùy chọn, do hệ thống tích hợp Open Gateway cấp và refresh; bridge chỉ chuyển tiếp header. Không có quy trình xin token hoặc xác thực local. Khởi động lại host khi đổi URL/path.

```powershell
kubectl -n camara-mcp logs deployment/camara-mcp -c server --tail=100 -f
kubectl -n camara-mcp get events --sort-by=.lastTimestamp
```

LOG_TO_FILE=false trong container; log MCP/tool/upstream OAuth/API ghi stderr với duration_ms, status, call_id/correlator. Không ghi body/key/token. Sau đổi cấu hình/secret/key cần rollout restart vì signer nạp tại startup. Stateless MCP có thể scale, nhưng cache OAuth upstream riêng mỗi Pod và cần tính hạn mức nhà mạng.

Docker local trên port3001:

```powershell
docker compose -f compose.local.yaml up -d --build
docker compose -f compose.local.yaml logs -f server
docker compose -f compose.local.yaml down
```

Compose chỉ bind localhost, không có xác thực local; dùng client URL http://localhost:3001/mcp.
