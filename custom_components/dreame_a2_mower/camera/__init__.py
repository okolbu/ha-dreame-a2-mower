"""Camera platform entry-point — registers the HTTP views and instantiates
all camera entities.

Phase 3c (2026-06-14) packaged the camera entity layer under ``camera/``. The
package ``__init__`` *is* the HA platform loader (HA imports
``custom_components.dreame_a2_mower.camera`` by name and calls
``async_setup_entry``) — a sibling ``camera.py`` module cannot coexist with this
package, so the thin entry lives here. The entity classes live in the
domain-grouped siblings ``map`` / ``lidar`` / ``wifi`` / ``photos`` and the HTTP
views in ``views``. The old root ``_camera_*.py`` paths remain as 1-line
re-export shims so deep test imports resolve unchanged.
"""
from __future__ import annotations

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ..const import DOMAIN
from ..coordinator import DreameA2MowerCoordinator

from .map import (
    DreameA2MapCamera,
    DreameA2PerMapCamera,
    DreameA2WorkLogCamera,
)
from .lidar import (
    DreameA2LidarTopDownCamera,
    DreameA2LidarTopDownFullCamera,
    DreameA2LidarSelectedCamera,
)
from .wifi import (
    DreameA2WifiSelectedCamera,
    DreameA2WifiPerMapCamera,
)
from .photos import (
    DreameA2AlbumPhotoCamera,
    DreameA2ObstaclePhotoCamera,
    DreameA2PersonPhotoCamera,
    DreameA2LatestVideoThumbCamera,
)
from .views import (
    LidarPcdDownloadView,
    LidarSelectedPcdView,
    MapImageView,
    PhotoFileView,
    VideoFileView,
    VideoThumbView,
    WorkLogImageView,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DreameA2MowerCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Register the auth-gated PCD download endpoint exactly once per HA
    # process. Subsequent config-entry reloads hit the same view (the
    # coordinator is looked up per-request).
    if not hass.data.setdefault(f"{DOMAIN}_views_registered", False):
        hass.http.register_view(LidarPcdDownloadView())
        hass.http.register_view(LidarSelectedPcdView())
        hass.http.register_view(MapImageView())
        hass.http.register_view(WorkLogImageView())
        hass.http.register_view(PhotoFileView())
        hass.http.register_view(VideoThumbView())
        hass.http.register_view(VideoFileView())
        hass.data[f"{DOMAIN}_views_registered"] = True

    # The "active map" follower camera (existing behaviour).
    entities: list[Camera] = [DreameA2MapCamera(coordinator)]
    # Defense-in-depth (T3-2 / R-5): cloud_state is None if the coordinator's
    # first cloud fetch failed (that path now raises ConfigEntryNotReady
    # before platforms are forwarded — see coordinator/_cloud_state.py:
    # _refresh_cloud_state_or_raise) or on a mid-life reload race. Either way
    # this must build zero per-map entities, not crash.
    maps_by_id = coordinator.cloud_state.maps_by_id if coordinator.cloud_state else {}
    # One per-map static camera per known map.
    for map_id in sorted(maps_by_id.keys()):
        entities.append(DreameA2PerMapCamera(coordinator, map_id))
    # LiDAR cameras — one per known map (top-down thumbnail + full-res).
    for map_id in sorted(maps_by_id.keys()):
        entities.append(DreameA2LidarTopDownCamera(coordinator, map_id=map_id))
        entities.append(DreameA2LidarTopDownFullCamera(coordinator, map_id=map_id))
    entities.append(DreameA2WorkLogCamera(coordinator))
    entities.append(DreameA2LidarSelectedCamera(coordinator))
    # Single picker-driven WiFi heatmap camera (follows DreameA2WifiViewSelect).
    entities.append(DreameA2WifiSelectedCamera(coordinator))
    # Per-map WiFi heatmap cameras — one per known map (v1.0.10a6+).
    # Renders the newest archive entry whose fingerprint-matcher
    # map_id equals the camera's map_id.
    for map_id in sorted(maps_by_id.keys()):
        entities.append(DreameA2WifiPerMapCamera(coordinator, map_id))

    # Album photo cameras — latest overall photo + latest person detection.
    entities.append(DreameA2AlbumPhotoCamera(coordinator))
    entities.append(DreameA2PersonPhotoCamera(coordinator))
    # Ephemeral obstacle-photo camera — latest obstacle_ephemeral photo
    # (Track B download path; archive populated by obstacle fetch [UNVERIFIED]).
    entities.append(DreameA2ObstaclePhotoCamera(coordinator))
    # Video thumbnail camera — latest video clip's thumbnail JPEG.
    entities.append(DreameA2LatestVideoThumbCamera(coordinator))

    async_add_entities(entities)
