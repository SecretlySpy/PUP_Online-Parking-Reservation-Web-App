class ActivityLogMiddleware:
    """Attach the client IP to each request for audit logging.

    Kept intentionally light — it only resolves the client IP (honouring a
    reverse-proxy ``X-Forwarded-For`` header) and stashes it on the request so
    :func:`core.models.log_activity` can record it. Domain events are logged
    explicitly by the views, not by sniffing every request here.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.client_ip = self._client_ip(request)
        return self.get_response(request)

    @staticmethod
    def _client_ip(request):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")
