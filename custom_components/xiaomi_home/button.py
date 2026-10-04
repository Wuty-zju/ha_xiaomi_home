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

import asyncio

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback, valid_entity_id
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry, entity_registry
from homeassistant.helpers.device_registry import DeviceInfo, DeviceEntryType
from homeassistant.helpers.entity_platform import (
    AddEntitiesCallback, async_get_current_platform)
from homeassistant.components.button import ButtonEntity

from .miot.miot_client import MIoTClient, MIoTManualScene
from .miot.miot_error import MIoTClientError
from .miot.miot_device import MIoTActionEntity, MIoTDevice
from .miot.miot_spec import MIoTSpecAction
from .miot.const import DOMAIN
from .miot.common import slugify_name


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

    if new_entities:
        async_add_entities(new_entities)
    if not config_entry.data.get('enable_manual_scenes', False):
        return

    client: MIoTClient = hass.data[DOMAIN]['miot_clients'][
        config_entry.entry_id]
    await client.load_manual_scenes_async()
    platform = async_get_current_platform()
    buttons: dict[str, ManualSceneButton] = {}
    sync_task = None
    unloaded = False

    async def sync_scenes() -> None:
        scenes = client.manual_scenes
        for key in list(buttons):
            if key not in scenes:
                entity = buttons.pop(key)
                if entity.entity_id in platform.entities:
                    await platform.async_remove_entity(entity.entity_id)
        added = []
        targets = await async_migrate_scene_ids(
            hass, config_entry, client, scenes)
        for key, scene in scenes.items():
            if key not in buttons:
                buttons[key] = ManualSceneButton(
                    client, key, scene, config_entry)
                buttons[key].entity_id = targets[key]
                added.append(buttons[key])
        if added:
            async_add_entities(added)

    @callback
    def schedule_sync() -> None:
        nonlocal sync_task
        if unloaded or set(buttons) == set(client.manual_scenes):
            return
        if sync_task is None or sync_task.done():
            sync_task = hass.async_create_task(sync_scenes())
            sync_task.add_done_callback(sync_done)

    @callback
    def sync_done(completed: asyncio.Task) -> None:
        if not completed.cancelled() and completed.exception() is None:
            schedule_sync()

    async def cancel_sync() -> None:
        nonlocal unloaded
        unloaded = True
        client.unsub_manual_scene_state('platform')
        if sync_task:
            sync_task.cancel()
            await asyncio.gather(sync_task, return_exceptions=True)

    client.sub_manual_scene_state('platform', schedule_sync)
    config_entry.async_on_unload(cancel_sync)
    sync_task = hass.async_create_task(sync_scenes())
    sync_task.add_done_callback(sync_done)
    await sync_task


def scene_entity_id(scene: MIoTManualScene, home_name: str) -> str:
    """Names affect initial IDs only; raw scene IDs remain execution inputs."""
    home = slugify_name(home_name) or 'home'
    scene_id = slugify_name(scene.scene_id) or 'scene'
    return ('button.mi_jia_chang_jing_shou_dong_kong_zhi_'
            f'{home}_{scene_id}')


async def async_migrate_scene_ids(
    hass: HomeAssistant, entry: ConfigEntry, client: MIoTClient,
    scenes: dict[str, MIoTManualScene] | None = None
) -> dict[str, str]:
    """Rename once using the registry, retaining a local reversible journal."""
    registry = entity_registry.async_get(hass)
    storage = client.miot_storage
    name = f"{entry.data['uid']}_{entry.data['cloud_server']}"
    journal = await storage.load_async(
        domain='miot_scene_registry', name=name, type_=dict)
    if journal is None:
        exists = await client.main_loop.run_in_executor(
            None, storage.file_exists, 'miot_scene_registry', f'{name}.dict')
        if exists:
            raise HomeAssistantError('Unreadable scene migration journal')
        journal = {'version': 1, 'entities': {}}
    if (not isinstance(journal, dict) or journal.get('version') != 1
            or isinstance(journal.get('version'), bool)
            or not isinstance(journal.get('entities'), dict)):
        raise HomeAssistantError('Invalid manual scene migration journal')
    records = journal['entities']
    targets = {}
    changed = False
    occupied = set(registry.entities) | set(hass.states.async_entity_ids())
    plan = []
    for key, scene in sorted((
            client.manual_scenes if scenes is None else scenes).items()):
        unique_id = f'{DOMAIN}.manual_scene.{key}'
        entity_id = registry.async_get_entity_id('button', DOMAIN, unique_id)
        item = registry.async_get(entity_id) if entity_id else None
        if item is not None and item.config_entry_id != entry.entry_id:
            raise HomeAssistantError('Manual scene identity belongs elsewhere')
        previous = records.get(unique_id)
        if previous is not None and (
                not isinstance(previous, dict)
                or not isinstance(previous.get('done'), bool)
                or not isinstance(previous.get('new'), str)
                or not valid_entity_id(previous['new'])
                or not previous['new'].startswith('button.')
                or (previous.get('old') is not None and (
                    not isinstance(previous['old'], str)
                    or not valid_entity_id(previous['old'])))):
            raise HomeAssistantError('Invalid manual scene migration record')
        if isinstance(previous, dict) and previous.get('done') is True:
            targets[key] = entity_id or previous['new']
            occupied.add(targets[key])
            continue
        home = entry.data['home_selected'][scene.home_id]
        target = scene_entity_id(scene, home.get('home_name') or scene.home_id)
        if isinstance(previous, dict):
            target = previous.get('new', target)
        if (not isinstance(target, str) or not valid_entity_id(target)
                or not target.startswith('button.')):
            raise HomeAssistantError('Invalid manual scene entity ID')
        base = target
        suffix = 0
        while target in occupied and target != entity_id:
            suffix += 1
            target = f'{base}_{key[:12]}' + (
                f'_{suffix}' if suffix > 1 else '')
        occupied.add(target)
        records[unique_id] = {
            'old': previous.get('old', entity_id) if isinstance(
                previous, dict) else entity_id,
            'new': target, 'done': item is None}
        targets[key] = target
        changed = True
        if item is not None:
            plan.append((unique_id, entity_id, target))
    if changed:
        # Save before touching the registry so interrupted migrations can be
        # resumed and old IDs remain available for a controlled rollback.
        if not await storage.save_async(
                domain='miot_scene_registry', name=name, data=journal):
            raise HomeAssistantError('Cannot save manual scene migration')
        applied = []
        committed = False
        try:
            for unique_id, old, new in plan:
                if old != new:
                    registry.async_update_entity(old, new_entity_id=new)
                    applied.append((old, new))
                records[unique_id]['done'] = True
            if plan:
                completion = client.main_loop.create_task(storage.save_async(
                    domain='miot_scene_registry', name=name, data=journal))
                try:
                    committed = await asyncio.shield(completion)
                except asyncio.CancelledError:
                    # Executor-backed saves cannot be cancelled reliably.
                    # Finish the journal before deciding whether to roll back.
                    committed = await completion
                    raise
                if not committed:
                    raise HomeAssistantError('Cannot finish scene migration')
        except (Exception, asyncio.CancelledError):
            if not committed:
                for old, new in reversed(applied):
                    registry.async_update_entity(new, new_entity_id=old)
            raise
    devices = device_registry.async_get(hass)
    entries = (devices.async_get_devices(
        identifiers={(DOMAIN, identifier)
                     for identifier in client.manual_scene_device_ids},
        config_entry_id=entry.entry_id)
               if hasattr(devices, 'async_get_devices') else
               device_registry.async_entries_for_config_entry(
                   devices, entry.entry_id))
    for device in entries:
        if any((DOMAIN, identifier) in device.identifiers
               for identifier in client.manual_scene_device_ids):
            identifiers = device.identifiers - {
                (DOMAIN, identifier)
                for identifier in client.manual_scene_device_ids}
            devices.async_update_device(
                device.id, new_identifiers=identifiers | {
                    (DOMAIN, client.manual_scene_device_id)},
                entry_type=DeviceEntryType.SERVICE)
    return targets


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
        self._attr_name = scene.scene_name
        self.entity_id = scene_entity_id(scene, home_name)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, client.manual_scene_device_id)},
            translation_key='manual_scenes',
            entry_type=DeviceEntryType.SERVICE)

    @property
    def available(self) -> bool:
        return self._client.manual_scene_available(self._scene_key)

    @property
    def icon(self) -> str:
        return {
            'local': 'mdi:hub-outline',
            'cloud': 'mdi:cloud-outline'
        }.get(self._client.manual_scene_route(self._scene_key),
              'mdi:cloud-off-outline')

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._client.sub_manual_scene_state(
            self._scene_key, self._handle_scene_state)
        self.async_on_remove(lambda: self._client.unsub_manual_scene_state(
            self._scene_key))

    @callback
    def _handle_scene_state(self) -> None:
        scene = self._client.manual_scenes.get(self._scene_key)
        if scene and scene.scene_name != self._attr_name:
            self._attr_name = scene.scene_name
            entity_registry.async_get(self.hass).async_update_entity(
                self.entity_id, original_name=scene.scene_name)
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
