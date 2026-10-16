"""Event platform for the Enable Banking integration: fires on new transactions."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import _transaction_sort_date
from .const import CONF_ASPSP_NAME, DOMAIN
from .coordinator import EnableBankingConfigEntry, EnableBankingCoordinator
from .models import AccountBalance

EVENT_TRANSACTION = "transaction"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EnableBankingConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the per-entry last-transaction event entity."""
    async_add_entities([EnableBankingLastTransactionEvent(entry.runtime_data)])


class EnableBankingLastTransactionEvent(CoordinatorEntity[EnableBankingCoordinator], EventEntity):
    """Fires a ``transaction`` event for each newly seen transaction.

    One entity per config entry, watching every account under it. The first
    update after setup only records what is already there (it comes from the
    disk cache), so HA restarts don't replay old transactions into
    automations. Later updates fire once per transaction not seen before,
    oldest first; the transaction fields plus ``iban`` and ``account_name``
    are the event attributes.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "last_transaction"
    _attr_attribution = "Data via Enable Banking AIS (PSD2)"

    def __init__(self, coordinator: EnableBankingCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_event_types = [EVENT_TRANSACTION]
        entry = coordinator.config_entry
        # Same unique_id as the pre-0.6.10 entity, so existing entity ids return.
        self._attr_unique_id = f"{entry.entry_id}_last_transaction"
        aspsp_name = entry.data.get(CONF_ASPSP_NAME, "Enable Banking")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=aspsp_name,
            manufacturer=aspsp_name,
            entry_type=DeviceEntryType.SERVICE,
        )
        self._seen: set[str] | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # The cache has already seeded coordinator.data; record it silently.
        self._process(fire=False)

    @callback
    def _handle_coordinator_update(self) -> None:
        if not self._process(fire=True):
            super()._handle_coordinator_update()

    def _process(self, *, fire: bool) -> bool:
        """Update the seen set; return True if any event was fired."""
        data = self.coordinator.data
        if data is None:
            return False
        current = _transactions_by_fingerprint(data.accounts.values())
        if self._seen is None or not fire:
            self._seen = set(current)
            return False
        new = [current[fp] for fp in current if fp not in self._seen]
        self._seen = set(current)
        new.sort(key=lambda item: _transaction_sort_date(item[0]))
        for txn, account in new:
            self._trigger_event(
                EVENT_TRANSACTION,
                {**txn, "iban": account.iban, "account_name": account.name},
            )
            self.async_write_ha_state()
        return bool(new)


def _transactions_by_fingerprint(
    accounts: Iterable[AccountBalance],
) -> dict[str, tuple[dict[str, Any], AccountBalance]]:
    out: dict[str, tuple[dict[str, Any], AccountBalance]] = {}
    for account in accounts:
        for txn in account.transactions:
            out[f"{account.stable_id}|{_fingerprint(txn)}"] = (txn, account)
    return out


def _fingerprint(txn: dict[str, Any]) -> str:
    # entry_reference is the bank's own id when present; the other fields
    # disambiguate banks that leave it out.
    return "|".join(
        str(txn.get(key, ""))
        for key in (
            "entry_reference",
            "booking_date",
            "value_date",
            "amount",
            "credit_debit_indicator",
            "counterparty",
            "remittance_information",
        )
    )
