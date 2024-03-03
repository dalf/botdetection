import os
import logging
import tomllib

from redis import Redis
from flask import Flask, render_template
from botdetection import install_botdetection, RouteFilter, Config, PredefinedRequestFilter

from api_rate_limit import api_rate_filter_request


app = Flask("botdetection demo")
logger = logging.getLogger(__name__)


# Registering the middleware
def get_config() -> Config:
    config_raw = {}
    try:
        with open("config.toml", "rb") as f:
            config_raw = tomllib.load(f)
    except IOError:
        print("Error loading config.toml")
        pass
    return Config(**config_raw)


redis = Redis.from_url("redis://localhost:6379/0")


route_filter = RouteFilter(
    {
        "/healthz": [],
        "/search": [
            PredefinedRequestFilter.http_accept,
            PredefinedRequestFilter.http_accept_encoding,
            PredefinedRequestFilter.http_accept_language,
            PredefinedRequestFilter.http_user_agent,
            api_rate_filter_request,
            PredefinedRequestFilter.ip_limit,
        ],
        "*": [
            PredefinedRequestFilter.http_user_agent,
        ],
    }
)


if not os.getenv("BOTDETECTION", "1") == "0":
    logger.warning("botdetection is installed")
    install_botdetection(app, redis, get_config(), route_filter)
else:
    logger.warning("botdetection is NOT installed")


@app.route("/")
def index():
    # no need to specify the link_token variable:
    # install_botdetection makes sure it is set in the template
    return render_template("index.html")


@app.route("/search")
def search():
    return {
        "results": [
            "aa",
            "bb",
            "cc",
        ]
    }


@app.route("/healthz")
def healthz():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run()
