# Docker và Kubernetes

Thực hiện các lệnh PowerShell từ `C:\camara-mcp\mcp-server`. Chỉ cần gói server; client ở lại máy host. Bộ manifest là mẫu dùng OAuth tích hợp hiện tại cho một client. Nó chưa tích hợp authorization server riêng của Open Gateway.

## 1. Chọn địa chỉ và registry

Chuẩn bị Docker daemon Linux đang chạy, registry có quyền push, cluster với kubectl đã cấu hình, Ingress controller, domain/DNS và chứng chỉ TLS.

- Thay `mcp.example.vn` trong configmap.yaml và ingress.yaml bằng domain thật; giữ endpoint `/mcp`.
- Thay `replace-ingress-class` trong ingress.yaml bằng IngressClass đang có (`kubectl get ingressclass`). Nếu Open Gateway có proxy riêng, dùng Service làm backend và cấu hình các route tương đương trên nền tảng thay cho Ingress này.
- Thay image trong deployment.yaml bằng registry/tag thực tế. Dùng tag bất biến hoặc digest khi release.
- MCP_CLIENT_ID trong ConfigMap phải khớp client ID được cấp cho bridge. Nó khác UPSTREAM_CLIENT_ID đăng ký tại Viettel.

Ingress chuyển tiếp Host công khai, Authorization và các header MCP; không rewrite `/mcp` hoặc redirect request OAuth. Cấu hình timeout ở controller tối thiểu 60 giây và không buffer SSE nếu dùng streaming, theo tài liệu controller của nền tảng. Client hiện có HTTP timeout 10 giây mặc định; tăng REQUEST_TIMEOUT_MS bên client nếu workflow cần lâu hơn.

## 2. Build và push

```powershell
docker build --platform linux/amd64 -t registry.example.com/camara/mcp-server:0.5.0 .
docker login registry.example.com
docker push registry.example.com/camara/mcp-server:0.5.0
```

Thay registry/tag trong cả lệnh và Deployment. Nếu node ARM64, build linux/arm64 hoặc image đa kiến trúc tương ứng. Dockerfile có hai stage: cài dependency/package trong builder; runtime chứa venv Linux và gateway.toml, chạy UID/GID 10001. GATEWAY_MODULES_FILE là đường dẫn tuyệt đối để package cài trong site-packages vẫn tìm đúng manifest.

.dockerignore loại .env, keys, venv Windows và file triển khai khỏi build context. Không đưa bí mật vào Dockerfile hoặc build arguments.

## 3. Tạo Secret và TLS

Kiểm tra context trước khi thao tác cluster:

```powershell
kubectl config current-context
kubectl apply -f k8s/namespace.yaml
```

Có thể dùng credential đang đăng ký trong server .env bằng script xuất đúng bốn trường cần thiết:

```powershell
.venv\Scripts\python.exe scripts\prepare_k8s_credentials.py
```

Script tạo k8s/credentials.env, không in giá trị và không ghi đè file đã có. Hoặc copy credentials.env.example sang credentials.env rồi điền credential deployment. MCP_CLIENT_SECRET và MCP_SIGNING_SECRET phải có ít nhất 32 ký tự. Không tự sinh key RSA mới thay key đã đăng ký.

```powershell
kubectl -n camara-mcp create secret generic camara-mcp-credentials --from-env-file=k8s/credentials.env
kubectl -n camara-mcp create secret generic camara-mcp-upstream-key --from-file=upstream-private.pem=keys/upstream-private.pem
kubectl -n camara-mcp create secret tls camara-mcp-tls --cert=C:/certs/fullchain.pem --key=C:/certs/privkey.pem
```

Các lệnh create dành cho lần đầu, không ghi đè Secret đang tồn tại. Đổi đường dẫn cert/key theo máy triển khai. Nếu đã dùng cert-manager hoặc dịch vụ quản lý secret của nền tảng, provision các Secret với đúng tên thay cho các lệnh trên. TLS Secret và private key ký JWT là hai cặp khóa độc lập.

Private key JWT được mount read-only tại `/run/secrets/upstream-private.pem`, mode 0440 và fsGroup 10001. Secret không có giá trị thật trong repository. Kubernetes Secret cần được quản trị với RBAC và encryption at rest; base64 không phải mã hóa. File credentials.env cục bộ cũng cần quyền truy cập hạn chế.

Nếu registry riêng yêu cầu pull credential, tạo imagePullSecret theo quy trình registry rồi thêm `imagePullSecrets` vào Pod spec. Không dùng credential push của quản trị viên làm mặc định cho workload.

## 4. Kiểm tra và triển khai

```powershell
kubectl kustomize k8s
kubectl apply --dry-run=server -k k8s
kubectl apply -k k8s
kubectl -n camara-mcp rollout status deployment/camara-mcp --timeout=180s
kubectl -n camara-mcp get pods,svc,ingress
```

Dry-run server cần cluster và quyền truy cập; kustomize chỉ render offline, không thay thế kiểm tra schema/admission của cluster. Bộ manifest không tự tạo credential/TLS Secret; tạo chúng trước Deployment.

Pod có startup/readiness/liveness probe tới `/health`, đặt Host=localhost:3000 để không bị kiểm tra Host chặn. Health chỉ xác nhận tiến trình và module đã nạp; không gọi nhà mạng và không chứng minh upstream đang khả dụng. Container có filesystem chỉ đọc, mount /tmp riêng, bỏ capabilities và không mount service-account token.

Sau khi DNS trỏ đúng ingress, kiểm tra discovery từ máy host:

```powershell
Invoke-RestMethod https://mcp.example.vn/.well-known/oauth-protected-resource/mcp
Invoke-RestMethod https://mcp.example.vn/.well-known/oauth-authorization-server
```

Metadata phải trả URL công khai, không localhost. Cập nhật mcp-client/.env:

```dotenv
MCP_SERVER_URL=https://mcp.example.vn/mcp
MCP_ISSUER=https://mcp.example.vn
MCP_TOKEN_URL=https://mcp.example.vn/oauth/token
MCP_CLIENT_ID=bank-client
MCP_CLIENT_SECRET=<khop-Secret-tren-cluster>
MCP_SCOPE=gateway:invoke
```

Khởi động lại MCP host để bridge dùng cấu hình mới. Chỉ client credential MCP được cấp cho bridge; không cấp private key hoặc credential upstream Viettel.

## Log, cập nhật và vận hành

```powershell
kubectl -n camara-mcp logs deployment/camara-mcp -c server --tail=100 -f
kubectl -n camara-mcp describe deployment camara-mcp
kubectl -n camara-mcp get events --sort-by=.lastTimestamp
```

LOG_LEVEL=info cung cấp log startup/shutdown và JSON log thời gian MCP/tool/OAuth/API qua stderr. LOG_TO_FILE=false trong container; dùng kubectl logs. duration_ms, status, cache_hit, lock_wait_ms, call_id và correlator hỗ trợ chẩn đoán. Access log đang tắt; body/credential không được ghi. Sau khi đổi code cần rebuild image và rollout Deployment. CrashLoop: kiểm tra credential, quyền đọc PEM, kid và cấu hình. ImagePullBackOff: kiểm tra image/tag và pull secret. Probe403: kiểm tra header Host trong probe. MCP403: kiểm tra Host/Origin proxy chuyển tiếp. Không in token/key vào log khi chẩn đoán.

Sau khi sửa ConfigMap/Secret/khóa, restart vì cấu hình và signer nạp tại startup:

```powershell
kubectl apply -k k8s
kubectl -n camara-mcp rollout restart deployment/camara-mcp
kubectl -n camara-mcp rollout status deployment/camara-mcp
```

Mặc định một replica. Có thể scale vì MCP HTTP stateless và mọi replica dùng cùng Secret ký token local; OAuth upstream cache/lock vẫn riêng mỗi Pod, không có cache/rate-limit phân tán. Cần kiểm tra hạn mức nhà mạng trước khi tăng replica. Một tool call chưa phải giao dịch có cơ chế exactly-once; không tự retry nghiệp vụ khi response mất.

Cluster cần egress HTTPS tới token endpoint và SIM Swap API của nhà mạng; cấu hình IP allowlist/proxy/CA theo onboarding. Bộ manifest không tự thay đổi NetworkPolicy hoặc các rule của nền tảng. Readiness không phụ thuộc cuộc gọi nhà mạng.

## Trạng thái kiểm tra

Docker daemon hiện không chạy trên máy phát triển, nên chưa build/chạy image. Đã render bộ manifest bằng kubectl kustomize; chưa apply hoặc dry-run server vào cluster. Kiểm thử cấu hình/probe và hồi quy Python được thực hiện riêng, không thay thế kiểm thử container Linux trên môi trường đích.

4 ca kiểm tra cấu hình/probe, manifest, xuất credential và runtime layout đã đạt; 8 ca hồi quy kiến trúc module cũng đạt. Không gọi API Viettel trong lần kiểm tra này.

Nguồn: [Docker Python guide](https://docs.docker.com/guides/python/), [Kubernetes probes](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/), [Secret](https://kubernetes.io/docs/concepts/configuration/secret/), [Ingress](https://kubernetes.io/docs/concepts/services-networking/ingress/).
