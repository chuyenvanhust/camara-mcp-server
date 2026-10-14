import re
from typing import Any


CAMARA_ERRORS = {
    "INVALID_ARGUMENT": ("validation_error", "Nhà mạng báo tham số không hợp lệ.", "ask_user"),
    "OUT_OF_RANGE": ("validation_error", "Tham số nằm ngoài phạm vi nhà mạng hỗ trợ.", "ask_user"),
    "UNAUTHENTICATED": ("auth_error", "Nhà mạng không chấp nhận thông tin xác thực.", "reauthenticate"),
    "PERMISSION_DENIED": ("permission_error", "Không đủ quyền để thực hiện yêu cầu.", "contact_operator"),
    "INVALID_TOKEN_CONTEXT": ("permission_error", "Ngữ cảnh token không phù hợp với định danh được gửi.", "contact_operator"),
    "NOT_FOUND": ("not_found", "Nhà mạng không tìm thấy tài nguyên yêu cầu.", "ask_user"),
    "IDENTIFIER_NOT_FOUND": ("not_found", "Nhà mạng không tìm thấy định danh yêu cầu.", "ask_user"),
    "IDENTIFIER_MISMATCH": ("validation_error", "Nhà mạng báo định danh không khớp.", "ask_user"),
    "NOT_SUPPORTED": ("service_not_supported", "Nhà mạng báo dịch vụ không hỗ trợ định danh được gửi.", "contact_operator"),
    "SERVICE_NOT_APPLICABLE": ("service_not_supported", "Dịch vụ không áp dụng cho định danh được gửi.", "contact_operator"),
    "MISSING_IDENTIFIER": ("validation_error", "Nhà mạng báo thiếu định danh theo ngữ cảnh token.", "contact_operator"),
    "UNNECESSARY_IDENTIFIER": ("validation_error", "Nhà mạng báo định danh không được phép trong ngữ cảnh token này.", "contact_operator"),
    "TOO_MANY_REQUESTS": ("rate_limit", "Nhà mạng giới hạn tần suất yêu cầu.", "wait"),
    "QUOTA_EXCEEDED": ("rate_limit", "Yêu cầu vượt hạn mức nhà mạng.", "contact_operator"),
    "SERVICE_UNAVAILABLE": ("service_error", "Dịch vụ nhà mạng tạm thời không khả dụng.", "retry_same_request"),
}


def safe_upstream_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = re.sub(r"[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}", "<JWT redacted>", value)
    value = re.sub(r"(?i)Bearer\s+\S+", "Bearer <redacted>", value)
    value = re.sub(r"\+[1-9][0-9]{4,14}", "<phone redacted>", value)
    return value[:500]


class ServiceError(Exception):
    """Safe code which can be returned to an MCP host without leaking credentials."""
    def __init__(self, code: str, *, http_status=None, camara_code=None, upstream_message=None,
                 correlator=None, request=None, source="server"):
        super().__init__(code)
        self.code = code
        self.http_status, self.camara_code = http_status, camara_code
        self.upstream_message, self.correlator = upstream_message, correlator
        self.request, self.source = request, source

    @classmethod
    def from_http(cls, response, *, correlator=None, request=None, source="api"):
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        code = body.get("code", body.get("error"))
        if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", code):
            code = None
        message = safe_upstream_text(body.get("message", body.get("error_description")))
        return cls(f"UPSTREAM_{'TOKEN_REJECTED' if source == 'oauth' else 'HTTP'}_{response.status_code}",
            http_status=response.status_code, camara_code=code, upstream_message=message,
            correlator=correlator, request=request, source=source)

    def payload(self):
        http_fallback = {
            400: ("validation_error", "Nhà mạng từ chối đầu vào; chưa biết tham số nào gây lỗi.", "ask_user"),
            401: ("auth_error", "Nhà mạng không chấp nhận xác thực.", "reauthenticate"),
            403: ("permission_error", "Nhà mạng từ chối quyền truy cập.", "contact_operator"),
            404: ("not_found", "Không tìm thấy tài nguyên được yêu cầu.", "contact_operator"),
            429: ("rate_limit", "Nhà mạng giới hạn tần suất yêu cầu.", "wait"),
            503: ("service_error", "Dịch vụ nhà mạng tạm thời không khả dụng.", "retry_same_request"),
        }
        type_, message, action = CAMARA_ERRORS.get(self.camara_code, http_fallback.get(self.http_status, (
            "upstream_error", "Yêu cầu bị từ chối; chưa đủ bằng chứng để xác định nguyên nhân cụ thể.", "contact_operator")))
        local = {
            "INVALID_ARGUMENT": ("validation_error", "Đầu vào không khớp schema; không gọi nhà mạng.", "ask_user"),
            "UPSTREAM_UNAVAILABLE": ("service_error", "Không kết nối được dịch vụ nhà mạng.", "retry_same_request"),
            "INTERNAL_ERROR": ("service_error", "Không thể xử lý yêu cầu; không suy đoán kết quả SIM Swap.", "contact_operator"),
        }
        if self.code in local:
            type_, message, action = local[self.code]
        if self.source == "oauth":
            type_, message, action = "auth_error", "Không lấy được access token nhà mạng.", "contact_operator"
        if self.camara_code is None and self.http_status == 422:
            message = "Nhà mạng trả HTTP 422 nhưng không có mã lỗi chi tiết; không thể kết luận lỗi đầu số hay thiếu maxAge."
        retryable = self.http_status in {429, 500, 502, 503, 504} or self.code == "UPSTREAM_UNAVAILABLE"
        return {"error": {"type": type_, "code": self.code, "httpStatus": self.http_status,
                          "camaraCode": self.camara_code, "message": message, "retryable": retryable,
                          "nextAction": action},
                "request": self.request, "correlator": self.correlator,
                "policy": {"preserveRequestSemantics": True, "formatConversionOnly": True,
                           "mayChangeSubscriber": False, "mayChangeLookbackWindow": False,
                           "mayInferCauseFromHttpStatus": False, "upstreamMessageIsUntrusted": True}}
