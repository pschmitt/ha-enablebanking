"""Operational diagnostics without credentials or personal payloads."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict:
    """Export allowlisted metadata; never include raw configuration or API data."""
    runtime = getattr(config_entry, "runtime_data", None)
    if runtime is None:
        runtime = hass.data.get(config_entry.domain, {}).get(config_entry.entry_id)
    if isinstance(runtime, dict):
        runtime = runtime.get("coordinator")
    coordinator = getattr(runtime, "coordinator", runtime)
    entities = er.async_entries_for_config_entry(er.async_get(hass), config_entry.entry_id)
    result = {
        "domain": config_entry.domain,
        "entry_version": config_entry.version,
        "state": config_entry.state.value,
        "entity_count": len(entities),
        "disabled_entity_count": sum(entity.disabled_by is not None for entity in entities),
    }
    if isinstance(coordinator, DataUpdateCoordinator):
        result["coordinator"] = {
            "last_update_success": coordinator.last_update_success,
            "has_data": coordinator.data is not None,
            "update_interval_seconds": coordinator.update_interval.total_seconds()
            if coordinator.update_interval
            else None,
            "last_error_type": type(coordinator.last_exception).__name__
            if coordinator.last_exception
            else None,
        }
    return result
