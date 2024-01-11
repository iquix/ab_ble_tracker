""" Device Tracker for AprilBrother BLE Gateway V4 """
import json
import logging
import voluptuous as vol
from typing import Optional, Set, Tuple

import homeassistant.components.mqtt as mqtt
from homeassistant.components.mqtt import CONF_STATE_TOPIC
from homeassistant.components.device_tracker import (
	PLATFORM_SCHEMA,
	SourceType,
)
from homeassistant.components.device_tracker.const import (
	CONF_TRACK_NEW,
	DEFAULT_TRACK_NEW,
)
from homeassistant.components.device_tracker.legacy import (
	YAML_DEVICES,
	async_load_config,
)
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import HomeAssistantType

DEPENDENCIES = ['mqtt']

_LOGGER = logging.getLogger(__name__)

BLE_PREFIX = "BLE_"
DEFAULT_STATE_TOPIC = "ab_ble"
EDS_PACKET_HEADER = "AAFE1516AAFE"
IBC_PACKET_HEADER = "1AFF4C000215"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
	{
		vol.Optional(CONF_TRACK_NEW): cv.boolean,
		vol.Optional(CONF_STATE_TOPIC, default=DEFAULT_STATE_TOPIC): cv.string,
	}
)


def is_ble_device(device):
	"""Check whether a device is a BLE device by its mac."""
	return device.mac and device.mac[:len(BLE_PREFIX)].upper() == BLE_PREFIX


async def see_device(hass, async_see, mac, device_name, rssi=None):
	"""Mark a device as seen."""
	attributes = {}
	if rssi is not None:
		attributes["rssi"] = rssi
	await async_see(
		mac=BLE_PREFIX+mac,
		host_name=device_name,
		attributes=attributes,
		source_type=SourceType.BLUETOOTH_LE,
	)


async def get_tracking_devices(hass: HomeAssistantType) -> Tuple[Set[str], Set[str]]:
	"""
	Load all known devices.

	We just need the devices so set consider_home and home range to 0
	"""
	yaml_path: str = hass.config.path(YAML_DEVICES)

	devices = await async_load_config(yaml_path, hass, 0)
	bluetooth_devices = [device for device in devices if is_ble_device(device)]

	devices_to_track: Set[str] = {
		device.mac[len(BLE_PREFIX):] for device in bluetooth_devices if device.track
	}
	devices_to_not_track: Set[str] = {
		device.mac[len(BLE_PREFIX):] for device in bluetooth_devices if not device.track
	}
	return devices_to_track, devices_to_not_track


async def async_setup_scanner(hass, config, async_see, discovery_info=None):
	"""Set up the AB BLE Scanner."""
	topic: string = config.get(CONF_STATE_TOPIC)
	# If track new devices is true discover new devices on startup.
	track_new: bool = config.get(CONF_TRACK_NEW, DEFAULT_TRACK_NEW)

	devices_to_track, devices_to_not_track = await get_tracking_devices(hass)

	#_LOGGER.debug("device to track {}".format(devices_to_track))
	#_LOGGER.debug("device to not track {}".format(devices_to_not_track))

	async def perform_bluetooth_update(data):
		p = {}
		try:
			p["mac"] = data[1].upper()
			p["rssi"] = data[2]
			p["adv"] = data[3].upper()
		except:
			return
		#_LOGGER.debug("perform_bluetooth_update({})".format(p))
		parsed_mac = parse_mac(p)
		device_name = BLE_PREFIX + parsed_mac.replace(":","")

		if track_new:
			if parsed_mac not in devices_to_track and parsed_mac not in devices_to_not_track:
				devices_to_track.add(parsed_mac)

		if parsed_mac in devices_to_track:
			await see_device(hass, async_see, parsed_mac, device_name, p["rssi"])


	def parse_mac(p):
		data = p["adv"]
		if EDS_PACKET_HEADER in data:
			startpos = data.find(EDS_PACKET_HEADER) + len(EDS_PACKET_HEADER)
			return "EDS_" + data[startpos+4:startpos+24].upper()
		elif IBC_PACKET_HEADER in data:
			startpos = data.find(IBC_PACKET_HEADER) + len(IBC_PACKET_HEADER)
			return "IBC_" + data[startpos:startpos+36].upper()
		return p["mac"]


	async def parseBLE(msg):
		try:
			devs = json.loads(msg.payload)["devices"]
		except:
			return
		#_LOGGER.debug("{}".format(devs))
		for x in devs:
			await perform_bluetooth_update(x)

	if not await mqtt.async_wait_for_mqtt_client(hass):
		_LOGGER.error("MQTT integration is not available. You should setup MQTT integration first.")
		return False

	await mqtt.async_subscribe(hass, topic, parseBLE, 0)

	return True
