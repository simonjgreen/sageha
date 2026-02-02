"""Constants for the Sage Coffee integration."""

DOMAIN = "sagecoffee"

# Configuration keys
CONF_REFRESH_TOKEN = "refresh_token"
CONF_BRAND = "brand"

# Machine type values
MACHINE_TYPE_SAGE = "sageCoffee"
MACHINE_TYPE_BREVILLE = "brevilleCoffee"

# Defaults
DEFAULT_NAME = "Sage Coffee"

# State mappings
STATE_READY = "ready"
STATE_WARMING = "warming"
STATE_ASLEEP = "asleep"

# Boiler IDs (from BES995 Oracle Dual Boiler)
BOILER_STEAM = 0
BOILER_BREW = 1

# Sensor types
SENSOR_STATE = "state"
SENSOR_BREW_TEMP = "brew_temp"
SENSOR_BREW_TARGET = "brew_target"
SENSOR_STEAM_TEMP = "steam_temp"
SENSOR_STEAM_TARGET = "steam_target"
SENSOR_THEME = "theme"
SENSOR_BRIGHTNESS = "brightness"
SENSOR_WORK_LIGHT = "work_light"
SENSOR_GRIND_SIZE = "grind_size"
SENSOR_VOLUME = "volume"
SENSOR_AUTO_OFF = "auto_off"

# Platforms
PLATFORMS = ["switch", "sensor", "text", "select", "number"]
