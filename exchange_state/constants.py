"""C1 Exchange State Manager — constants."""

VALID_MODES = ("paper", "testnet", "live")

# Single TTL for the whole ExchangeSnapshot (v2 review point #3: one
# snapshot, one cache, one TTL — not six categories each with their own
# clock to keep in sync).
DEFAULT_SNAPSHOT_TTL_SECONDS = 3.0

DEFAULT_EXCHANGE = "binance"
DEFAULT_ACCOUNT_ID = "default"
