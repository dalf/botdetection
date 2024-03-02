import tomllib

from redis import Redis
from flask import Flask, render_template
from botdetection import install_botdetection, ComposedFilter, Config, BotFilter

from api_rate_limit import api_rate_filter_request


app = Flask("botdetection demo")


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


composed_filter = ComposedFilter(
    {
        "/healthz": [],
        "/search": [
            BotFilter.http_accept,
            BotFilter.http_accept_encoding,
            BotFilter.http_accept_language,
            BotFilter.http_user_agent,
            api_rate_filter_request,
            BotFilter.ip_limit,
        ],
        "*": [
            BotFilter.http_user_agent,
        ],
    }
)


install_botdetection(app, redis, get_config(), composed_filter)


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
