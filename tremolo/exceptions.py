# Copyright (c) 2023 nggit

from .lib.http_exception import (  # noqa: F401
    TremoloException,
    HTTPException,
    BadRequest,
    Unauthorized,
    Forbidden,
    NotFound,
    MethodNotAllowed,
    RequestTimeout,
    PreconditionFailed,
    PayloadTooLarge,
    RangeNotSatisfiable,
    ExpectationFailed,
    TooManyRequests,
    InternalServerError,
    ServiceUnavailable,
    WebSocketException,
    WebSocketClientClosed,
    WebSocketServerClosed
)


class ASGIException(TremoloException):
    message = 'ASGIException'


class LifespanError(ASGIException):
    pass


class LifespanProtocolUnsupported(ASGIException):
    message = 'ASGI Lifespan Protocol is not supported by your application'
