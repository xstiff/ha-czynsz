"""Stałe integracji Czynsz."""
from datetime import timedelta

DOMAIN = "czynsz"
CONF_USER = "user"

UPDATE_INTERVAL = timedelta(hours=6)
STORAGE_VERSION = 1

EVENT_NEW_SETTLEMENT = "czynsz_new_settlement"
SERVICE_REFRESH = "refresh"
PORTAL_URL = "https://tomojdom.pl"
PAYMENT_URL = "https://tomojdom.pl/"  # strona główna — płatność BLIK / szybki przelew
