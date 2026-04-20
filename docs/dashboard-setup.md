# Starter dashboard — copy-paste setup

This integration ships a ready-to-use Lovelace dashboard at
[`dashboards/mower.yaml`](../dashboards/mower.yaml). It showcases the
map camera with replay overlay, the 3D WebGL LiDAR card, mower state,
problem indicators, and live telemetry in one view.

Home Assistant does not auto-install integration dashboards, so this
is a two-minute manual copy. The steps below are identical on HA OS,
HA Core, Supervised, and Docker installs.

## 1. Copy the YAML

With HA running, drop the starter file into your config dir. If you
have SSH access:

```bash
mkdir -p /config/dashboards/dreame_a2_mower
curl -o /config/dashboards/dreame_a2_mower/dashboard.yaml \
  https://raw.githubusercontent.com/okolbu/ha-dreame-a2-mower/main/dashboards/mower.yaml
```

Or via the File Editor / Studio Code Server add-on: create
`dashboards/dreame_a2_mower/dashboard.yaml` and paste the contents of
[`dashboards/mower.yaml`](../dashboards/mower.yaml).

## 2. Register the dashboard

Add this to your main `configuration.yaml` (merge with an existing
`lovelace:` block if you have one):

```yaml
lovelace:
  # `storage` mode preserves the default dashboard's UI-edit behaviour.
  # You can use `yaml` mode here if you prefer your whole dashboard
  # set to be YAML-managed.
  mode: storage

  dashboards:
    dreame-a2-mower:
      mode: yaml
      title: Mower
      icon: mdi:robot-mower
      show_in_sidebar: true
      filename: dashboards/dreame_a2_mower/dashboard.yaml
```

## 3. Restart Home Assistant

Settings → System → Restart Home Assistant. After the restart a
**Mower** entry appears in the sidebar. The dashboard is live; edit
the YAML file on disk or fork it into your own config freely.

## Customising

- **Entity IDs:** The YAML uses the entity IDs from a fresh install
  (`select.dreame_a2_mower_replay_session`, etc.). If you're on an
  older install and the replay picker is named `select.replay_session`
  without the device prefix, either rename it in
  *Settings → Devices & Services → Entities* or edit the YAML to
  match.
- **Panel layout:** Replace `type: picture-entity` with your favourite
  map card if you prefer (but note the xiaomi-vacuum-map-card
  incompatibility documented in the main README and the v17 commit
  message — picture-entity is the safe default).
- **Adding more cards:** HA's Lovelace YAML reference applies —
  [Home Assistant Lovelace docs](https://www.home-assistant.io/dashboards/yaml/).

## Rolling back

Delete `dashboards/dreame_a2_mower/dashboard.yaml`, remove the
`dreame-a2-mower:` block from `configuration.yaml`'s
`lovelace.dashboards`, and restart HA. The sidebar entry disappears;
no other state changes.
