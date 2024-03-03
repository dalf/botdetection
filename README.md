# botdetection

## Run example


Using rye

```
rye sync
cd example
python app.py
```

Without rye:

```
python -m venv venv
. ./venv/bin/activate
pip install -e .
cd example
python app.py
```

To disable the bot detection (raw Flask application):

```sh
BOTDETECTION=0 python app.y
```

To disable Redis:

```sh
REDIS=0 python app.y
```
