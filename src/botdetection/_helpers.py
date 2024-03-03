# SPDX-License-Identifier: AGPL-3.0-or-later
# lint: pylint
# pylint: disable=missing-module-docstring, invalid-name
from __future__ import annotations

import logging
from ipaddress import (
    IPv4Network,
    IPv6Network,
    IPv4Address,
    IPv6Address,
    ip_network,
)
import flask
import werkzeug

from . import RequestInfo
from .config import Config

logger = logging.getLogger("botdetection")


def dump_request(request: flask.Request):
    return (
        request.path
        + " || X-Forwarded-For: %s" % request.headers.get("X-Forwarded-For")
        + " || X-Real-IP: %s" % request.headers.get("X-Real-IP")
        + " || form: %s" % request.form
        + " || Accept: %s" % request.headers.get("Accept")
        + " || Accept-Language: %s" % request.headers.get("Accept-Language")
        + " || Accept-Encoding: %s" % request.headers.get("Accept-Encoding")
        + " || Content-Type: %s" % request.headers.get("Content-Type")
        + " || Content-Length: %s" % request.headers.get("Content-Length")
        + " || Connection: %s" % request.headers.get("Connection")
        + " || User-Agent: %s" % request.headers.get("User-Agent")
    )


def too_many_requests(request_info: RequestInfo, log_msg: str) -> werkzeug.Response | None:
    """Returns a HTTP 429 response object and writes a ERROR message to the
    'botdetection' logger.  This function is used in part by the filter methods
    to return the default ``Too Many Requests`` response.

    """

    logger.debug("BLOCK %s: %s", request_info.network.compressed, log_msg)
    return flask.make_response(("Too Many Requests", 429))


def get_network(config: Config, real_ip: IPv4Address | IPv6Address) -> IPv4Network | IPv6Network:
    """Returns the (client) network of whether the real_ip is part of."""

    if real_ip.version == 6:
        prefix = config.real_ip.ipv6_prefix
    else:
        prefix = config.real_ip.ipv4_prefix
    network = ip_network(f"{real_ip}/{prefix}", strict=False)
    # logger.debug("get_network(): %s", network.compressed)
    return network


_logged_errors = []


def _log_error_only_once(err_msg):
    if err_msg not in _logged_errors:
        logger.error(err_msg)
        _logged_errors.append(err_msg)


def get_real_ip(config: Config, request: flask.Request) -> str:
    """Returns real IP of the request.  Since not all proxies set all the HTTP
    headers and incoming headers can be faked it may happen that the IP cannot
    be determined correctly.

    .. sidebar:: :py:obj:`flask.Request.remote_addr`

       SearXNG uses Werkzeug's ProxyFix_ (with it default ``x_for=1``).

    This function tries to get the remote IP in the order listed below,
    additional some tests are done and if inconsistencies or errors are
    detected, they are logged.

    The remote IP of the request is taken from (first match):

    - X-Forwarded-For_ header
    - `X-real-IP header <https://github.com/searxng/searxng/issues/1237#issuecomment-1147564516>`__
    - :py:obj:`flask.Request.remote_addr`

    .. _ProxyFix:
       https://werkzeug.palletsprojects.com/middleware/proxy_fix/

    .. _X-Forwarded-For:
      https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/X-Forwarded-For

    """

    forwarded_for = request.headers.get("X-Forwarded-For")
    real_ip = request.headers.get("X-Real-IP")
    remote_addr = request.remote_addr
    # logger.debug(
    #     "X-Forwarded-For: %s || X-Real-IP: %s || request.remote_addr: %s", forwarded_for, real_ip, remote_addr
    # )

    if not forwarded_for:
        _log_error_only_once("X-Forwarded-For header is not set!")
    else:
        forwarded_for = [x.strip() for x in forwarded_for.split(",")]
        forwarded_for = forwarded_for[-min(len(forwarded_for), config.real_ip.x_for)]

    if not real_ip:
        _log_error_only_once("X-Real-IP header is not set!")

    if forwarded_for and real_ip and forwarded_for != real_ip:
        logger.warning(
            "IP from X-Real-IP (%s) is not equal to IP from X-Forwarded-For (%s)",
            real_ip,
            forwarded_for,
        )

    if forwarded_for and remote_addr and forwarded_for != remote_addr:
        logger.warning(
            "IP from WSGI environment (%s) is not equal to IP from X-Forwarded-For (%s)",
            remote_addr,
            forwarded_for,
        )

    if real_ip and remote_addr and real_ip != remote_addr:
        logger.warning(
            "IP from WSGI environment (%s) is not equal to IP from X-Real-IP (%s)",
            remote_addr,
            real_ip,
        )

    request_ip = forwarded_for or real_ip or remote_addr or "0.0.0.0"
    # logger.debug("get_real_ip() -> %s", request_ip)
    return request_ip
