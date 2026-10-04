# -*- coding: utf-8 -*-
"""
Copyright (C) 2024 Xiaomi Corporation.

The ownership and intellectual property rights of Xiaomi Home Assistant
Integration and related Xiaomi cloud service API interface provided under this
license, including source code and object code (collectively, "Licensed Work"),
are owned by Xiaomi. Subject to the terms and conditions of this License, Xiaomi
hereby grants you a personal, limited, non-exclusive, non-transferable,
non-sublicensable, and royalty-free license to reproduce, use, modify, and
distribute the Licensed Work only for your use of Home Assistant for
non-commercial purposes. For the avoidance of doubt, Xiaomi does not authorize
you to use the Licensed Work for any other purpose, including but not limited
to use Licensed Work to develop applications (APP), Web services, and other
forms of software.

You may reproduce and distribute copies of the Licensed Work, with or without
modifications, whether in source or object form, provided that you must give
any other recipients of the Licensed Work a copy of this License and retain all
copyright and disclaimers.

Xiaomi provides the Licensed Work on an "AS IS" BASIS, WITHOUT WARRANTIES OR
CONDITIONS OF ANY KIND, either express or implied, including, without
limitation, any warranties, undertakes, or conditions of TITLE, NO ERROR OR
OMISSION, CONTINUITY, RELIABILITY, NON-INFRINGEMENT, MERCHANTABILITY, or
FITNESS FOR A PARTICULAR PURPOSE. In any event, you are solely responsible
for any direct, indirect, special, incidental, or consequential damages or
losses arising from the use or inability to use the Licensed Work.

Xiaomi reserves all rights not expressly granted to you in this License.
Except for the rights expressly granted by Xiaomi under this License, Xiaomi
does not authorize you in any form to use the trademarks, copyrights, or other
forms of intellectual property rights of Xiaomi and its affiliates, including,
without limitation, without obtaining other written permission from Xiaomi, you
shall not use "Xiaomi", "Mijia" and other words related to Xiaomi or words that
may make the public associate with Xiaomi in any form to publicize or promote
the software or hardware devices that use the Licensed Work.

Xiaomi has the right to immediately terminate all your authorization under this
License in the event:
1. You assert patent invalidation, litigation, or other claims against patents
or other intellectual property rights of Xiaomi or its affiliates; or,
2. You make, have made, manufacture, sell, or offer to sell products that knock
off Xiaomi or its affiliates' products.

Button entities for Xiaomi Home.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.button import ButtonEntity

from .miot.miot_client import MIoTClient, MIoTManualScene
from .miot.miot_error import MIoTClientError
from .miot.miot_device import MIoTActionEntity, MIoTDevice
from .miot.miot_spec import MIoTSpecAction
from .miot.const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up a config entry."""
    device_list: list[MIoTDevice] = hass.data[DOMAIN]['devices'][
        config_entry.entry_id]

    new_entities = []
    for miot_device in device_list:
        for action in miot_device.action_list.get('button', []):
            new_entities.append(Button(miot_device=miot_device, spec=action))

    if config_entry.data.get('enable_manual_scenes', False):
        client: MIoTClient = hass.data[DOMAIN]['miot_clients'][
            config_entry.entry_id]
        await client.load_manual_scenes_async()
        new_entities.extend(
            ManualSceneButton(client, key, scene, config_entry)
            for key, scene in client.manual_scenes.items())

    if new_entities:
        async_add_entities(new_entities)


class Button(MIoTActionEntity, ButtonEntity):
    """Button entities for Xiaomi Home."""

    def __init__(self, miot_device: MIoTDevice, spec: MIoTSpecAction) -> None:
        """Initialize the Button."""
        super().__init__(miot_device=miot_device, spec=spec)
        # Use default device class

    async def async_press(self) -> None:
        """Press the button."""
        return await self.action_async()


class ManualSceneButton(ButtonEntity):
    """A manual scene, routed by the entry's existing MIoT client."""
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self, client: MIoTClient, key: str, scene: MIoTManualScene,
        config_entry: ConfigEntry
    ) -> None:
        self._client = client
        self._scene_key = key
        self._attr_unique_id = f'{DOMAIN}.manual_scene.{key}'
        home = config_entry.data['home_selected'][scene.home_id]
        home_name = home.get('home_name') or scene.home_id
        self._attr_name = f'{home_name} {scene.scene_name}'
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, client.manual_scene_device_id)},
            translation_key='manual_scenes')

    @property
    def available(self) -> bool:
        return self._client.manual_scene_available(self._scene_key)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._client.sub_manual_scene_state(
            self._scene_key, self._handle_scene_state)
        self.async_on_remove(lambda: self._client.unsub_manual_scene_state(
            self._scene_key))

    @callback
    def _handle_scene_state(self) -> None:
        self.async_write_ha_state()

    async def async_press(self) -> None:
        try:
            await self._client.run_manual_scene_async(self._scene_key)
        except MIoTClientError as err:
            key = err.message if err.message in (
                'scene_unavailable', 'scene_busy', 'scene_failed',
                'scene_result_unknown') else 'scene_result_unknown'
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key=key) from None
