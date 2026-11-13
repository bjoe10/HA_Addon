#!/usr/bin/env python3
"""Test: Art-Net-Nodes aus einer configuration.yaml lesen (Ausschnitt wie beim Nutzer, mit !include-Tags).
Aufruf: python3 dev/test_config.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import config  # noqa: E402

SAMPLE = """
automation: !include automations.yaml
frontend:
  themes: !include_dir_merge_named themes
light:
  - platform: artnet_led
    host: 10.0.0.144
    max_fps: 25
    universes: # Support for multiple universes
      1: # Nr of Universe
        send_partial_universe: false
        devices:
          - channel: 1 # first channel
            name: pan # name
            channel_size: 16bit
          - channel: 3
            name: tilt
            channel_size: 16bit
          - channel: 5
            name: color
          - channel: 6
            name: Grobo
          - channel: 7
            name: strobe
          - channel: 8
            name: dimmer
          - channel: 9
            name: motor speed
          - channel: 10
            name: auto mode
          - channel: 11
            name: config mode
  - platform: artnet_led
    host: 10.0.0.146
    universes:
      1:
        devices:
          - channel: 1
            name: my_dimmer422
          - channel: 16
            name: color2
          - channel: 17
            name: Grobo2
          - channel: 18
            name: strobe2
          - channel: 19
            name: dimmer2
          - channel: 12
            name: pan2
            channel_size: 16bit
          - channel: 14
            name: tilt2
            channel_size: 16bit
  - platform: artnet_led
    host: 10.0.0.195
    universes:
      1:
        devices:
          - channel: 23
            name: Laser_mode
sensor:
  - platform: history_stats
    name: pan
"""

heads, source = config.heads_from_text(SAMPLE)
assert heads[1][0] == "10.0.0.144" and heads[1][2]["pan"] == 1 and heads[1][2]["gobo"] == 6, heads[1]
assert heads[2][0] == "10.0.0.146" and heads[2][2]["pan"] == 12 and heads[2][2]["dimmer"] == 19, heads[2]
assert heads[2][2]["speed"] == 20, "fehlender Kanal kommt aus dem Rückfall"
assert source == {1: "configuration.yaml", 2: "configuration.yaml"}, source
heads, source = config.heads_from_text(None)
assert source == {1: "Standardwerte", 2: "Standardwerte"}
print("config: Node-Erkennung ok")
