"""Constants for the Sage Coffee integration."""

from sagecoffee import APP_BREVILLE, APP_LELIT, APP_SAGE

DOMAIN = "sagecoffee"

# Configuration keys
CONF_REFRESH_TOKEN = "refresh_token"
CONF_BRAND = "brand"

# Legacy configuration keys (migrated on setup)
CONF_MACHINE_TYPE_LEGACY = "machine_type"

# Machine type values (the brand's app identifier)
MACHINE_TYPE_SAGE = APP_SAGE
MACHINE_TYPE_BREVILLE = APP_BREVILLE
MACHINE_TYPE_LELIT = APP_LELIT

# Brand choices offered in the config flow
BRAND_OPTIONS = [
    {"label": "Sage", "value": MACHINE_TYPE_SAGE},
    {"label": "Breville", "value": MACHINE_TYPE_BREVILLE},
    {"label": "Lelit", "value": MACHINE_TYPE_LELIT},
]

# Defaults
DEFAULT_NAME = "Sage Coffee"

# State mappings
STATE_READY = "ready"
STATE_WARMING = "warming"
STATE_ASLEEP = "asleep"

# Sensor types
SENSOR_STATE = "state"
SENSOR_BREW_TEMP = "brew_temp"
SENSOR_BREW_TARGET = "brew_target"
SENSOR_STEAM_TEMP = "steam_temp"
SENSOR_STEAM_TARGET = "steam_target"
SENSOR_THEME = "theme"
SENSOR_BRIGHTNESS = "brightness"
SENSOR_GRIND_SIZE = "grind_size"
SENSOR_VOLUME = "volume"
SENSOR_AUTO_OFF = "auto_off"

# Platforms
PLATFORMS = ["switch", "sensor", "text", "select", "number", "light"]
