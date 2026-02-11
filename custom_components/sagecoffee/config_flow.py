"""Config flow for Sage Coffee integration."""

from __future__ import annotations

import logging
from typing import Any

from sagecoffee.auth import DEFAULT_CLIENT_ID, AuthClient
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_BRAND,
    CONF_REFRESH_TOKEN,
    DOMAIN,
    MACHINE_TYPE_BREVILLE,
    MACHINE_TYPE_SAGE,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL)
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
        vol.Required(CONF_BRAND): SelectSelector(
            SelectSelectorConfig(
                options=[
                    {"label": "Sage", "value": MACHINE_TYPE_SAGE},
                    {"label": "Breville", "value": MACHINE_TYPE_BREVILLE},
                ]
            )
        ),
    }
)

STEP_TOKEN_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_REFRESH_TOKEN): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
        vol.Required(CONF_BRAND): SelectSelector(
            SelectSelectorConfig(
                options=[
                    {"label": "Sage", "value": MACHINE_TYPE_SAGE},
                    {"label": "Breville", "value": MACHINE_TYPE_BREVILLE},
                ]
            )
        ),
    }
)


class SageCoffeeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Sage Coffee."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._refresh_token: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step - choose auth method."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["password", "token"],
        )

    async def async_step_password(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle username/password authentication."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                auth_client = AuthClient(client_id=DEFAULT_CLIENT_ID)
                tokens = await auth_client.password_realm_login(
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
                self._refresh_token = tokens.refresh_token

                # Use auth0 subject as unique ID to prevent duplicates
                unique_id = tokens.auth0_sub()
                if unique_id:
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()

                # Create the config entry
                return self.async_create_entry(
                    title="Sage Coffee",
                    data={
                        CONF_REFRESH_TOKEN: self._refresh_token,
                        CONF_BRAND: user_input[CONF_BRAND],
                    },
                )

            except AbortFlow:
                raise
            except Exception as err:
                _LOGGER.exception("Authentication failed: %s", err)
                errors["base"] = "invalid_auth"

        return self.async_show_form(
            step_id="password",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_token(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle refresh token authentication."""
        errors: dict[str, str] = {}

        if user_input is not None:
            refresh_token = user_input[CONF_REFRESH_TOKEN]

            try:
                # Validate the token by trying to refresh it
                auth_client = AuthClient(client_id=DEFAULT_CLIENT_ID)
                tokens = await auth_client.refresh(refresh_token)

                # Use the potentially rotated token
                self._refresh_token = tokens.refresh_token or refresh_token

                # Use auth0 subject as unique ID to prevent duplicates
                unique_id = tokens.auth0_sub()
                if unique_id:
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title="Sage Coffee",
                    data={
                        CONF_REFRESH_TOKEN: self._refresh_token,
                        CONF_BRAND: user_input[CONF_BRAND],
                    },
                )

            except AbortFlow:
                raise
            except Exception as err:
                _LOGGER.exception("Token validation failed: %s", err)
                errors["base"] = "invalid_auth"

        return self.async_show_form(
            step_id="token",
            data_schema=STEP_TOKEN_DATA_SCHEMA,
            errors=errors,
            description_placeholders={
                "bootstrap_command": "sagectl bootstrap --username your.email@example.com"
            },
        )
