"""world.runtime.statistics — read-only aggregate numbers over a
`WorldState` plus a `StateCache`'s bookkeeping. Nothing here mutates
anything; `compute_statistics` is a pure function of its two inputs."""

from dataclasses import dataclass

from world.runtime.models import WorldState
from world.runtime.state_cache import StateCache


@dataclass(frozen=True)
class WorldStatistics:
    active_rooms: int
    inactive_rooms: int
    active_agents: int
    inactive_agents: int
    total_missions: int
    total_notifications: int
    portfolio_position_count: int
    portfolio_symbols: tuple[str, ...]
    cache_hit_ratio: float
    refresh_count: int
    last_rebuild_seconds: float
    update_frequency_per_second: float

    def to_dict(self) -> dict:
        return {
            "activeRooms": self.active_rooms,
            "inactiveRooms": self.inactive_rooms,
            "activeAgents": self.active_agents,
            "inactiveAgents": self.inactive_agents,
            "totalMissions": self.total_missions,
            "totalNotifications": self.total_notifications,
            "portfolioPositionCount": self.portfolio_position_count,
            "portfolioSymbols": list(self.portfolio_symbols),
            "cacheHitRatio": self.cache_hit_ratio,
            "refreshCount": self.refresh_count,
            "lastRebuildSeconds": self.last_rebuild_seconds,
            "updateFrequencyPerSecond": self.update_frequency_per_second,
        }


def compute_statistics(state: WorldState, cache: StateCache) -> WorldStatistics:
    active_rooms = sum(1 for r in state.rooms if r.is_active)
    active_agents = sum(1 for a in state.agents if a.is_active)

    return WorldStatistics(
        active_rooms=active_rooms,
        inactive_rooms=len(state.rooms) - active_rooms,
        active_agents=active_agents,
        inactive_agents=len(state.agents) - active_agents,
        total_missions=len(state.missions),
        total_notifications=len(state.notifications),
        portfolio_position_count=len(state.portfolio),
        portfolio_symbols=tuple(p.symbol for p in state.portfolio),
        cache_hit_ratio=cache.metrics.hit_ratio,
        refresh_count=cache.metrics.refresh_count,
        last_rebuild_seconds=cache.metrics.last_rebuild_seconds,
        update_frequency_per_second=cache.metrics.update_frequency_per_second,
    )
