from enum import Enum

import botdetection.http_accept
import botdetection.http_accept_encoding
import botdetection.http_accept_language
import botdetection.http_connection
import botdetection.http_user_agent
import botdetection.ip_limit
from ._helpers import too_many_requests

from ipaddress import (
    IPv4Network,
    IPv6Network,
    ip_address,
)
from logging import getLogger
from flask import Flask, Response, Request, request, render_template_string, make_response

import werkzeug
from redis import Redis

from botdetection._helpers import get_network, get_real_ip
from botdetection.config import Config
from botdetection.redislib import RedisLib
import botdetection.link_token as link_token
import botdetection.ip_lists as ip_lists


__all__ = [
    "too_many_requests",
    "Config",
    "BotFilter",
    "RedisLib",
    "install_botdetection",
]


logger = getLogger(__name__)


class Filter:
    def __call__(
        self,
        redis: RedisLib,
        config: Config,
        network: IPv4Network | IPv6Network,
        request: Request,
    ) -> werkzeug.Response | None:
        return None


def install_botdetection(app: Flask, redis: Redis, config: Config, filter: Filter):
    app.botdetection = BotDetection(app, redis, config, filter)


class BotFilter(Enum):
    http_accept = botdetection.http_accept.filter_request
    http_accept_encoding = botdetection.http_accept_encoding.filter_request
    http_accept_language = botdetection.http_accept_language.filter_request
    http_connection = botdetection.http_connection.filter_request
    http_user_agent = botdetection.http_user_agent.filter_request
    ip_limit = botdetection.ip_limit.filter_request


class ComposedFilter(Filter):
    def __init__(self, filters: dict[str, BotFilter]):
        self.filters = filters

    def __call__(
        self,
        redis: RedisLib,
        config: Config,
        network: IPv4Network | IPv6Network,
        request: Request,
    ) -> werkzeug.Response | None:
        f_list = self.filters.get(request.path)
        if f_list is None:
            f_list = self.filters.get("*")
        if isinstance(f_list, list):
            for f in f_list:
                if isinstance(f, BotFilter):
                    f = f.value
                val = f(redis, config, network, request)
                if val is not None:
                    return val
        return None


class BotDetection:
    def __init__(self, app: Flask, redis: Redis, config: Config, filter: Filter):
        self.app = app
        self.config = config
        self.filter = filter
        prefix = config.botdetection.redis.prefix
        secret = config.botdetection.redis.secret_hash
        self.redislib = RedisLib(redis, prefix, secret)
        self.register_jinja_globals()
        self.register_endpoints()
        self.register_before_request()

    def register_before_request(self):
        @self.app.before_request
        def before_request():
            real_ip = ip_address(get_real_ip(self.config, request))
            network = get_network(self.config, real_ip)
            if network.is_link_local:
                return None
            # block- & pass- lists
            #
            # 1. The IP of the request is first checked against the pass-list; if the IP
            #    matches an entry in the list, the request is not blocked.
            # 2. If no matching entry is found in the pass-list, then a check is made against
            #    the block list; if the IP matches an entry in the list, the request is
            #    blocked.
            # 3. If the IP is not in either list, the request is not blocked.

            match, msg = ip_lists.pass_ip(real_ip, self.config)
            if match:
                logger.warning("PASS %s: matched PASSLIST - %s", network.compressed, msg)
                return None

            match, msg = ip_lists.block_ip(real_ip, self.config)
            if match:
                logger.error("BLOCK %s: matched BLOCKLIST - %s", network.compressed, msg)
                return make_response(("IP is on BLOCKLIST - %s" % msg, 429))

            # HERE : use self.config to pick the filters according to the route
            response = self.filter(self.redislib, self.config, network, request)
            if response is not None:
                return response

            return None

    # def is_bot_request(self, environ):
    #     # Implement your bot detection logic based on self.config
    #     # Example:
    #     user_agent = environ.get('HTTP_USER_AGENT', '')
    #     return 'bot' in user_agent.lower()

    def register_jinja_globals(self):
        template_string = """
        <link rel="stylesheet" href="{{ url_for('client_token', token=link_token) }}" type="text/css" />
        """

        @self.app.context_processor
        def inject_bot_detector():
            def botdetection_html_header():
                html = render_template_string(template_string, link_token=link_token.get_token(self.redislib, self.config))
                # find the equivalent of flask.Markup and use it
                return html

            return {"botdetection_html_header": botdetection_html_header}

    def register_endpoints(self):
        @self.app.route("/client<token>.css", methods=["GET"])
        def client_token(token=None):
            link_token.ping(self.redislib, self.config, request, token)
            return Response("", mimetype="text/css")
