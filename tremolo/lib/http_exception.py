# Copyright (c) 2023 nggit

class HTTPException(Exception):
    code = 500
    message = 'Internal Server Error'

    def __init__(self, *args, code=None, message=None, cause=None):
        self.args = args

        if isinstance(code, int):
            self.code = code

        if isinstance(message, str):
            self.message = message

        if isinstance(cause, Exception):
            self.__cause__ = cause

    def __str__(self):
        if self.args:
            return ' '.join(self.args)

        return self.message

class BadRequest(HTTPException):
    code = 400
    message = 'Bad Request'

class Unauthorized(HTTPException):
    code = 401
    message = 'Unauthorized'

class Forbidden(HTTPException):
    code = 403
    message = 'Forbidden'

class NotFound(HTTPException):
    code = 404
    message = 'Not Found'

class MethodNotAllowed(HTTPException):
    code = 405
    message = 'Method Not Allowed'

class RequestTimeout(HTTPException):
    code = 408
    message = 'Request Timeout'

class PayloadTooLarge(HTTPException):
    code = 413
    message = 'Payload Too Large'

class URITooLong(HTTPException):
    code = 414
    message = 'URI Too Long'

class RangeNotSatisfiable(HTTPException):
    code = 416
    message = 'Range Not Satisfiable'

class ExpectationFailed(HTTPException):
    code = 417
    message = 'Expectation Failed'

class InternalServerError(HTTPException):
    pass

class ServiceUnavailable(HTTPException):
    code = 503
    message = 'Service Unavailable'
