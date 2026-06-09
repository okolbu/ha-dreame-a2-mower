"""Camera entities for album (Patrol + AI-obstacle) photos.

[dreame-app-implementation-guide-2026-06-09.md] Two entities: latest album photo
overall, and latest person/guard-detection (``_person.jpg``) photo. The app only
distinguishes type on the photo itself, not in the list, so ``_person`` is the
only reliable discriminator we expose.

Both cameras are pull-only: ``async_camera_image`` reads the archive fresh on
every call, so they automatically reflect new photos without a coordinator
listener or access_token rotation (there is no selection-change event to react
to — the archive monotonically gains entries).
"""
from __future__ import annotations

from homeassistant.components.camera import Camera

from ._devices import mower_device_info, mower_unique_id
from .coordinator import DreameA2MowerCoordinator


class _BasePhotoCamera(Camera):
    """Shared base for album and person-detection photo cameras.

    Pull-only: ``async_camera_image`` reads the archive fresh on every call.
    No coordinator listener — photos are only added (never replaced), so the
    availability check correctly reflects the current archive state without any
    extra subscription machinery.
    """

    _attr_has_entity_name = True
    _attr_content_type = "image/jpeg"

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        Camera.__init__(self)
        self.coordinator = coordinator
        self._attr_device_info = mower_device_info(coordinator)

    def _latest_bytes(self) -> bytes | None:
        raise NotImplementedError

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        return await self.coordinator.hass.async_add_executor_job(self._latest_bytes)

    @property
    def available(self) -> bool:
        return self._latest_bytes() is not None


class DreameA2AlbumPhotoCamera(_BasePhotoCamera):
    """Serves the most-recently-archived photo (any type).

    entity_id: ``camera.dreame_a2_mower_album_photo``
    """

    _attr_name = "Latest photo"

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "album_photo")

    def _latest_bytes(self) -> bytes | None:
        e = self.coordinator.photo_archive.latest()
        if e is None:
            return None
        return self.coordinator.photo_archive.read_bytes(e.filename)


class DreameA2PersonPhotoCamera(_BasePhotoCamera):
    """Serves the most-recently-archived photo flagged as person detection.

    entity_id: ``camera.dreame_a2_mower_person_photo``
    """

    _attr_name = "Latest person detection"

    def __init__(self, coordinator: DreameA2MowerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = mower_unique_id(coordinator, "person_photo")

    def _latest_bytes(self) -> bytes | None:
        e = self.coordinator.photo_archive.latest_person()
        if e is None:
            return None
        return self.coordinator.photo_archive.read_bytes(e.filename)
