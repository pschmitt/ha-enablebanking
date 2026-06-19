"""Event platform for Enable Banking — fires on new bank transactions."""

from __future__ import annotations

import logging

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ASPSP_NAME, DOMAIN
from .coordinator import EnableBankingCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Enable Banking last-transaction event entity."""
    coordinator: EnableBankingCoordinator = config_entry.runtime_data
    async_add_entities([EnableBankingLastTransactionEvent(coordinator)])


class EnableBankingLastTransactionEvent(
    CoordinatorEntity[EnableBankingCoordinator], EventEntity
):
    """Event entity that fires when a new Enable Banking transaction is detected.

    Watches all accounts under this config entry and fires on the most recently
    booked transaction across all of them.  The HA event type is always
    ``"transaction"``; bank-specific details are in the event attributes.
    """

    _attr_has_entity_name = True
    _attr_event_types = ["transaction"]
    _attr_name = "Last transaction"
    _attr_icon = "mdi:bank-transfer"

    def __init__(self, coordinator: EnableBankingCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_last_transaction"
        aspsp_name = entry.data.get(CONF_ASPSP_NAME, "Enable Banking")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=aspsp_name,
            manufacturer=aspsp_name,
            entry_type=DeviceEntryType.SERVICE,
        )
        self._last_fingerprint: str | None = None

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        if data is None:
            super()._handle_coordinator_update()
            return

        result = _latest_transaction(data.accounts)
        if result is None:
            super()._handle_coordinator_update()
            return

        tx, iban = result
        fingerprint = _fingerprint(tx)

        if self._last_fingerprint is None:
            # First update after (re)start — record silently to avoid spurious
            # automations every time HA restarts.
            self._last_fingerprint = fingerprint
        elif fingerprint != self._last_fingerprint:
            self._last_fingerprint = fingerprint
            attrs = dict(tx)
            attrs["iban"] = iban
            self._trigger_event("transaction", attrs)
            return  # _trigger_event already calls async_write_ha_state

        super()._handle_coordinator_update()


def _latest_transaction(accounts: dict) -> tuple[dict, str] | None:
    """Return (transaction_dict, iban) for the most recently booked transaction."""
    best_tx: dict | None = None
    best_date = ""
    best_iban = ""
    for ab in accounts.values():
        for tx in (ab.transactions or []):
            date = tx.get("booking_date") or tx.get("value_date") or ""
            if date > best_date:
                best_date = date
                best_tx = tx
                best_iban = getattr(ab, "iban", "")
    return (best_tx, best_iban) if best_tx is not None else None


def _fingerprint(tx: dict) -> str:
    return (
        f"{tx.get('booking_date', '')}|"
        f"{tx.get('entry_reference', '')}|"
        f"{tx.get('amount', '')}|"
        f"{tx.get('currency', '')}"
    )
