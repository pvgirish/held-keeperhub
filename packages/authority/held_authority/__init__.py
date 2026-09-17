"""Bounded authority inventory: who can move the customer's funds, within a declared scope."""
from .inventory import AuthorityInventory, InventoryError, collect, from_report

__all__ = ["AuthorityInventory", "InventoryError", "collect", "from_report"]
