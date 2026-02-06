# Sage Coffee Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

Home Assistant custom integration for Sage/Breville connected coffee machines.

## Features

- **Power Control**: Turn your coffee machine on (wake) and off (sleep)
- **Real-time State Monitoring**: See if your machine is ready, warming up, or asleep
- **Temperature Sensors**: Monitor brew and steam boiler temperatures
- **Configuration Sensors**: View theme, brightness, grind size, and more

## Supported Machines

This integration uses the [sagecoffee](https://github.com/simonjgreen/sagecoffee) library and supports WiFi-connected Sage/Breville machines. At time of publication this is only:

- Sage/breville Oracle Dual Boiler (BES995)

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots in the top right corner
3. Select "Custom repositories"
4. Add `https://github.com/simonjgreen/sageha` as a custom repository (Category: Integration)
5. Click "Add"
6. Find "Sage Coffee" in the HACS integrations list and install it
7. Restart Home Assistant

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

### Number

| Entity                | Description                                |
| --------------------- | ------------------------------------------ |
| Display Brightness    | Set display brightness percentage          |
| Work Light Brightness | Set Cup warmer light brightness percentage |
| Volume                | Set volume level percentage                |

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
| Work Light Brightness    | Cup warmer light brightness percentage         |
| Grind Size               | Current grinder setting                        |
| Volume                   | Volume level percentage                        |
| Auto-off Time            | Idle time before auto-sleep (minutes)          |

## Actions

### Enable wake schedule
```yaml
action: sagecoffee.set_wake_schedule
data:
  serial: A1BUAESA252503225
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
  serial: A1BUAESA252503225
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

### Connection Issues

- The integration uses WebSocket for real-time updates; ensure your Home Assistant instance can reach `iot-api-ws.breville.com`
- Check Home Assistant logs for detailed error messages

### Machine Not Found

- Ensure your machine is paired with your Sage/Breville account
- Try re-pairing the machine using the official Sage/Breville app

## Contributing

Contributions are welcome! Please open an issue or pull request on the [GitHub repository](https://github.com/simonjgreen/sageha).

## License

This project is licensed under the MIT License.

## Disclaimer

This is an unofficial integration. It is not affiliated with, endorsed by, or supported by Breville or Sage. Use at your own risk.
