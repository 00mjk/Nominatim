# SPDX-License-Identifier: GPL-2.0-only
#
# This file is part of Nominatim. (https://nominatim.org)
#
# Copyright (C) 2023 by the Nominatim developer community.
# For a full list of authors see the git log.
"""
Server implementation using the sanic webserver framework.
"""
from typing import Any, Optional, Mapping, Callable, cast, Coroutine
from pathlib import Path

from sanic import Request, HTTPResponse, Sanic
from sanic.exceptions import SanicException
from sanic.response import text as TextResponse

from nominatim.api import NominatimAPIAsync
import nominatim.api.v1 as api_impl
from nominatim.config import Configuration

class ParamWrapper(api_impl.ASGIAdaptor):
    """ Adaptor class for server glue to Sanic framework.
    """

    def __init__(self, request: Request) -> None:
        self.request = request


    def get(self, name: str, default: Optional[str] = None) -> Optional[str]:
        return cast(Optional[str], self.request.args.get(name, default))


    def get_header(self, name: str, default: Optional[str] = None) -> Optional[str]:
        return cast(Optional[str], self.request.headers.get(name, default))


    def error(self, msg: str, status: int = 400) -> SanicException:
        exception = SanicException(msg, status_code=status)

        return exception


    def create_response(self, status: int, output: str) -> HTTPResponse:
        return TextResponse(output, status=status, content_type=self.content_type)


    def config(self) -> Configuration:
        return cast(Configuration, self.request.app.ctx.api.config)


def _wrap_endpoint(func: api_impl.EndpointFunc)\
       -> Callable[[Request], Coroutine[Any, Any, HTTPResponse]]:
    async def _callback(request: Request) -> HTTPResponse:
        return cast(HTTPResponse, await func(request.app.ctx.api, ParamWrapper(request)))

    return _callback


def get_application(project_dir: Path,
                    environ: Optional[Mapping[str, str]] = None) -> Sanic:
    """ Create a Nominatim sanic ASGI application.
    """
    app = Sanic("NominatimInstance")

    app.ctx.api = NominatimAPIAsync(project_dir, environ)

    if app.ctx.api.config.get_bool('CORS_NOACCESSCONTROL'):
        from sanic_cors import CORS # pylint: disable=import-outside-toplevel
        CORS(app)

    legacy_urls = app.ctx.api.config.get_bool('SERVE_LEGACY_URLS')
    for name, func in api_impl.ROUTES:
        endpoint = _wrap_endpoint(func)
        app.add_route(endpoint, f"/{name}", name=f"v1_{name}_simple")
        if legacy_urls:
            app.add_route(endpoint, f"/{name}.php", name=f"v1_{name}_legacy")

    return app
