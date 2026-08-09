class ApplicationError(RuntimeError):
    code = "application_error"
    status_code = 400


class NotFoundError(ApplicationError):
    code = "not_found"
    status_code = 404


class UnsafeSourceUrlError(ApplicationError):
    code = "unsafe_source_url"
    status_code = 422


class UnsupportedMediaError(ApplicationError):
    code = "unsupported_media"
    status_code = 415


class ExternalServiceUnavailableError(ApplicationError):
    code = "external_service_unavailable"
    status_code = 503
