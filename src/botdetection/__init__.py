from dataclasses import dataclass
from enum import Enum

import botdetection.http_accept
import botdetection.http_accept_encoding
import botdetection.http_accept_language
import botdetection.http_connection
import botdetection.http_user_agent
import botdetection.ip_limit
from ._helpers import (
    get_network,
    get_real_ip,
    too_many_requests,
)

from ipaddress import (
    IPv4Address,
    IPv6Address,
    IPv4Network,
    IPv6Network,
    ip_address,
)
from logging import getLogger
from flask import Flask, Response, Request, request, render_template_string, make_response

import werkzeug
from redis import Redis

from botdetection.config import Config
from botdetection.redislib import RedisLib
from botdetection.link_token import LinkToken, get_link_token
import botdetection.ip_lists as ip_lists


__all__ = [
    "too_many_requests",
    "Config",
    "RequestContext",
    "RequestInfo",
    "PredefinedRequestFilter",
    "RedisLib",
    "install_botdetection",
]


logger = getLogger(__name__)


@dataclass
class RequestContext:
    config: Config
    redislib: RedisLib | None
    link_token: LinkToken | None


@dataclass
class RequestInfo:
    real_ip: IPv4Address | IPv6Address
    network: IPv4Network | IPv6Network


class RequestFilter:
    def __call__(
        self,
        context: RequestContext,
        request_info: RequestInfo,
        request: Request,
    ) -> werkzeug.Response | None:
        return None


def install_botdetection(app: Flask, redis: Redis, config: Config, request_filter: RequestFilter):
    app.botdetection = BotDetection(app, redis, config, request_filter)


class PredefinedRequestFilter(Enum):
    http_accept = botdetection.http_accept.filter_request
    http_accept_encoding = botdetection.http_accept_encoding.filter_request
    http_accept_language = botdetection.http_accept_language.filter_request
    http_connection = botdetection.http_connection.filter_request
    http_user_agent = botdetection.http_user_agent.filter_request
    ip_limit = botdetection.ip_limit.filter_request


class RouteFilter(RequestFilter):
    def __init__(self, filters: dict[str, list[RequestFilter | PredefinedRequestFilter]]):
        self.filters = filters

    def __call__(
        self,
        context: RequestContext,
        request_info: RequestInfo,
        request: Request,
    ) -> werkzeug.Response | None:
        # FIXME: request.path is not the route
        f_list = self.filters.get(request.path)
        if f_list is None:
            f_list = self.filters.get("*")
        if isinstance(f_list, list):
            for f in f_list:
                if isinstance(f, PredefinedRequestFilter):
                    f = f.value
                val = f(context, request_info, request)
                if val is not None:
                    return val
        return None


class BotDetection:
    def __init__(self, app: Flask, redis: Redis, config: Config, request_filter: RequestFilter):
        self.app = app
        self.config = config
        self.request_filter = request_filter
        prefix = config.botdetection.redis.prefix
        secret = config.botdetection.redis.secret_hash
        self.redislib = RedisLib(redis, prefix, secret) if redis else None
        self.register_jinja_globals()
        self.register_endpoints()
        self.register_before_request()

    def register_before_request(self):
        @self.app.before_request
        def before_request():
            real_ip = ip_address(get_real_ip(self.config, request))
            network = get_network(self.config, real_ip)
            request_info = RequestInfo(real_ip, network)

            link_token = get_link_token(self.redislib, self.config, request_info, request)
            context = RequestContext(self.config, self.redislib, link_token)

            request.botdetection_context = context
            request.botdetection_request_info = request_info

            if request_info.network.is_link_local and not context.config.botdetection.ip_limit.filter_link_local:
                logger.debug(
                    "network %s is link-local -> not monitored by ip_limit method",
                    request_info.network.compressed,
                )
                return None

            # block- & pass- lists
            #
            # 1. The IP of the request is first checked against the pass-list; if the IP
            #    matches an entry in the list, the request is not blocked.
            # 2. If no matching entry is found in the pass-list, then a check is made against
            #    the block list; if the IP matches an entry in the list, the request is
            #    blocked.
            # 3. If the IP is not in either list, the request is not blocked.
            match, msg = ip_lists.pass_ip(request_info.real_ip, self.config)
            if match:
                logger.warning("PASS %s: matched PASSLIST - %s", request_info.network.compressed, msg)
                return None

            match, msg = ip_lists.block_ip(request_info.real_ip, self.config)
            if match:
                logger.error("BLOCK %s: matched BLOCKLIST - %s", request_info.network.compressed, msg)
                return make_response(("IP is on BLOCKLIST - %s" % msg, 429))

            # apply the filter(s)
            response = self.request_filter(context, request_info, request)
            if response is not None:
                return response

            # the request is accepted
            return None

    def register_jinja_globals(self):
        template_string = """
        <link rel="stylesheet" href="{{ url_for('client_token', token=link_token) }}" type="text/css" />
        """

        @self.app.context_processor
        def inject_bot_detector():
            def botdetection_html_header():
                token = request.botdetection_context.link_token.get_token()
                html = render_template_string(template_string, link_token=token)
                # find the equivalent of flask.Markup and use it
                return html

            return {"botdetection_html_header": botdetection_html_header}

    def register_endpoints(self):
        @self.app.route("/client<token>.css", methods=["GET"])
        def client_token(token=None):
            request.botdetection_context.link_token.ping(token)
            return Response("", mimetype="text/css")
