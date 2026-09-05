# Sage Coffee Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Default-41BDF5.svg)](https://github.com/hacs/integration)
[![Tests](https://github.com/simonjgreen/sageha/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/simonjgreen/sageha/actions/workflows/tests.yml)
[![Validate](https://github.com/simonjgreen/sageha/actions/workflows/validate.yaml/badge.svg?branch=main)](https://github.com/simonjgreen/sageha/actions/workflows/validate.yaml)

Home Assistant custom integration for Sage/Breville connected coffee machines.

## Features

- **Power Control**: Turn your coffee machine on (wake) and off (sleep)
- **Real-time State Monitoring**: See if your machine is ready, warming up, or asleep
- **Temperature Sensors**: Monitor brew and steam boiler temperatures
- **Configuration Sensors**: View theme, brightness, grind size, and more
- **Low-water Fault Sensor**: Detect reported low-water and empty-tank warnings
- **Wake Schedule**: See when your machine is next scheduled to switch on automatically
- **Firmware Version**: Check the installed firmware version from the device page

## Supported Machines

This integration uses the [sagecoffee](https://github.com/simonjgreen/sagecoffee) library and supports WiFi-connected Sage/Breville machines. At time of publication this is only:

- Sage/breville Oracle Dual Boiler (BES995)

## Installation

### HACS (Recommended)

Sage Coffee is included in the default HACS repository, so no custom repository setup is required.

1. Open HACS in Home Assistant
2. Search for "Sage Coffee"
3. Click on it and select "Download"
4. Restart Home Assistant

### Manual Installation

1. Download the `custom_components/sagecoffee` folder from this repository
2. Copy it to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services**
2. Click **Add Integration**
3. Search for "Sage Coffee"
4. Choose your authentication method:
   - **Email and Password**: Enter your Sage/Breville account credentials
   - **Refresh Token**: If you already have a refresh token from the sagectl CLI tool
   - **Machine Type**: Select Sage (Europe) or Breville (Rest of the world)

### Getting a Refresh Token (Advanced)

If you prefer not to enter your password in Home Assistant, you can use the sagectl CLI tool to obtain a refresh token:

```bash
pip install sagecoffee
sagectl bootstrap --username your.email@example.com
```

Then paste the refresh token from `~/.config/sagecoffee/config.toml` into Home Assistant.

## Entities

For each coffee machine, the integration creates:

### Switch

| Entity | Description                               |
| ------ | ----------------------------------------- |
| Power  | Turn the machine on (wake) or off (sleep) |

### Text

| Entity | Description                               |
| ------ | ----------------------------------------- |
| Name   | Set appliance name                        |

### Select

| Entity | Description                               |
| ------ | ----------------------------------------- |
| Theme  | Set theme (dark/light)                    |

### Light

| Entity     | Description                                      |
| ---------- | ------------------------------------------------ |
| Work Light | Cup warmer illumination — on/off with brightness |

### Number

| Entity             | Description                       |
| ------------------ | --------------------------------- |
| Display Brightness | Set display brightness percentage |
| Volume             | Set volume level percentage       |

### Binary Sensors

| Entity    | Description                                         |
| --------- | --------------------------------------------------- |
| Low Water | Problem indicator for low-water or empty-tank faults |

Low Water turns on for error code `31102` (low water) or `29120` (empty tank),
and off when a valid reported error list contains neither code. Missing or
malformed error data makes the sensor unavailable unless a recognized water
fault is present. Updates depend on Sage/Breville cloud reports and can be
delayed. This is not a water-level percentage.

### Sensors

| Entity                   | Description                                    |
| ------------------------ | ---------------------------------------------- |
| State                    | Current machine state (ready, warming, asleep) |
| Brew Temperature         | Current brew boiler temperature                |
| Brew Target Temperature  | Target brew boiler temperature                 |
| Steam Temperature        | Current steam boiler temperature               |
| Steam Target Temperature | Target steam boiler temperature                |
| Theme                    | Display theme (dark/light)                     |
| Display Brightness       | Display brightness percentage                  |
| Grind Size               | Current grinder setting                        |
| Volume                   | Volume level percentage                        |
| Auto-off Time            | Idle time before auto-sleep (minutes)          |
| Next Wake Time           | Next scheduled automatic wake time             |
| Wake Schedule            | Raw wake schedule summary                      |
| Temperature Unit         | Configured temperature unit                    |
| Timezone                 | Configured machine timezone                    |
| Remote Wake              | Whether remote wake is enabled                 |
| Last Paired              | Last cloud pairing timestamp                   |
| State Report Version     | Latest WebSocket state report version          |
| Firmware Version         | Installed firmware version (diagnostic)        |
| MCU Firmware Version     | Installed MCU firmware version (diagnostic)    |
| OTA Service Version      | Installed OTA service version (diagnostic)     |
| SOM Image Version        | Installed SOM image version (diagnostic)       |
| Errors Count             | Number of appliance errors reported            |

## Actions

### Enable wake schedule
```yaml
action: sagecoffee.set_wake_schedule
data:
  serial: YOUR_SERIAL_NUMBER
  hours: 7
  minutes: 30
  days:
    - mon
    - tue
    - wed
    - thu
    - fri
```

The `days` field is optional. If omitted, the schedule runs every day. The `enabled` field (default `true`) can be set to `false` to create a disabled schedule.

### Disable wake schedule

```yaml
action: sagecoffee.disable_wake_schedule
data:
  serial: YOUR_SERIAL_NUMBER
```

## Automations

Here are some example automations you can create:

### Wake up machine before your morning alarm

```yaml
automation:
  - alias: "Morning Coffee Warmup"
    trigger:
      - platform: time
        at: "06:30:00"
    condition:
      - condition: time
        weekday:
          - mon
          - tue
          - wed
          - thu
          - fri
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.oracle_dual_boiler_power
```

### Notification when machine is ready

```yaml
automation:
  - alias: "Coffee Machine Ready"
    trigger:
      - platform: state
        entity_id: sensor.oracle_dual_boiler_state
        to: "ready"
    action:
      - service: notify.mobile_app
        data:
          message: "Coffee machine is ready!"
```

## Troubleshooting

### Authentication Issues

- Ensure your Sage/Breville account credentials are correct
- Try using the sagectl CLI tool to verify your credentials work
- Check that your machine is connected to WiFi and visible in the Sage/Breville app

### Device appears in app but not in integration

If you can see your machine in the official Sage/Breville mobile app but it's not appearing in Home Assistant:

- Check that you're using a **regular email and password account** for authentication
- Google account sign-in does not bind your identities between the app and the integration
- If you only have a Google account, consider creating a password-protected account through the Sage/Breville account settings and use that for Home Assistant

### Connection Issues

- The integration uses WebSocket for real-time updates; ensure your Home Assistant instance can reach `iot-api-ws.breville.com`
- Check Home Assistant logs for detailed error messages

### Machine Not Found

- Ensure your machine is paired with your Sage/Breville account
- Try re-pairing the machine using the official Sage/Breville app

## Removal

1. Go to **Settings** → **Devices & Services**
2. Find "Sage Coffee" and click on it
3. Click the three dots menu and select **Delete**
4. If installed via HACS, also remove it there: go to **HACS** → find "Sage Coffee" → click the three dots menu → **Remove**
5. Restart Home Assistant if prompted

## Contributing

Contributions are welcome! Please open an issue or pull request on the [GitHub repository](https://github.com/simonjgreen/sageha).

## License

This project is licensed under the MIT License.

## Disclaimer

This is an unofficial integration. It is not affiliated with, endorsed by, or supported by Breville or Sage. Use at your own risk.
