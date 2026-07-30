"""AssetSource + AssetRegistry.

`AssetRegistry` is the concrete piece the ASSET SYSTEM requirement
describes: "Support OpenGameArt, LPC, Kenney, future custom assets
without changing code." It holds a mapping of `AssetSource ->
AssetLoader` and dispatches `resolve(asset_id)` to whichever
registered loader claims the id via `AssetLoader.can_load`. Adding a
new source is: implement `AssetLoader`, call `register_loader` — no
changes to this class or to any renderer."""

from enum import Enum

from world.frontend.interfaces.asset_loader import AssetLoader


class AssetSource(str, Enum):
    OPENGAMEART = "opengameart"
    LPC = "lpc"
    KENNEY = "kenney"
    CUSTOM = "custom"


class UnresolvedAssetError(LookupError):
    """Raised when no registered loader claims a given asset id."""


class AssetRegistry:
    """Concrete, engine-agnostic asset registry. No source is
    registered by default — Phase W3 ships the registry with zero
    loaders wired in, since no concrete `AssetLoader` exists yet."""

    def __init__(self) -> None:
        self._loaders: dict[AssetSource, AssetLoader] = {}
        self._cache: dict[str, object] = {}

    def register_loader(self, source: AssetSource, loader: AssetLoader) -> None:
        self._loaders[source] = loader

    def registered_sources(self) -> list[AssetSource]:
        return list(self._loaders.keys())

    def resolve(self, asset_id: str) -> object:
        """Return a cached or freshly loaded engine-native asset
        handle. Raises `UnresolvedAssetError` if no registered loader
        claims `asset_id`."""
        if asset_id in self._cache:
            return self._cache[asset_id]

        for loader in self._loaders.values():
            if loader.can_load(asset_id):
                handle = loader.load(asset_id)
                self._cache[asset_id] = handle
                return handle

        raise UnresolvedAssetError(
            f"no registered AssetLoader claims asset_id {asset_id!r} "
            f"(registered sources: {[s.value for s in self._loaders]})"
        )

    def clear_cache(self) -> None:
        self._cache.clear()
