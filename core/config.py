import json
from opentdx.tdxClient import TdxClient
TDX_CLIENT = TdxClient()
CONFIG_DATA = json.load(open("core/config.json"))

MAX_CONCURRENCY = int(CONFIG_DATA["MAX_CONCURRENCY"])
PROXY_CONFIG = CONFIG_DATA["PROXY_CONFIG"]
THS_CONFIG = CONFIG_DATA["THS_CONFIG"]
DB_CONFIG = CONFIG_DATA["DB_CONFIG"]
