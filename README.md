# Dashboard Notifications integration

The backend for a shared, persistent Home Assistant notification feed. Install this repository through HACS as an integration, restart Home Assistant, then add **Dashboard Notifications** from **Settings → Devices & services**.

Create topics in the integration's **Configure** screen. Topics receive a generated UUID; use that UUID in automations and card YAML. The companion dashboard card has a topic picker, so normal dashboard configuration does not require copying IDs.

```yaml
- action: dashboard_notifications.create_timed
  data:
    topic: 4efb1c3a-0000-0000-0000-000000000000
    key: washer_cycle
    title: Washer
    message: Cycle complete
    severity: success
    expires_in:
      minutes: 30
  response_variable: created_notification

- action: dashboard_notifications.dismiss
  data:
    key: washer_cycle
```

Each create action returns `id` when Home Assistant is asked for an action response. A notification without a `key` appends to the feed; the same `key` replaces its existing item while retaining its generated `id`.

Use `persistent: true` on any create action to prevent card dismissal. Persistent items may still expire when created with `create_timed` or `create_scheduled_expiry`, and they remain removable through `dashboard_notifications.dismiss` by `id` or `key`.

## Notification actions

Add an `actions` list to any create action to show icon buttons on the matching card notification. The list accepts one or more actions; the card displays one button for each action. Every action requires an `icon`, user-facing `label`, and Home Assistant service in `action`. `target` and `data` are passed to that service as usual.

Set `dismiss: true` to remove the notification only after its action service succeeds. If the service fails, the notification remains visible and the dashboard shows an error.

```yaml
- action: dashboard_notifications.create
  data:
    topic: 4efb1c3a-0000-0000-0000-000000000000
    key: rubbish_reminder
    title: Rubbish collection
    message: Put the bins out tonight.
    severity: info
    actions:
      - icon: mdi:lightbulb-on-outline
        label: Turn on porch light
        action: light.turn_on
        target:
          entity_id: light.porch
        data:
          brightness_pct: 100
        dismiss: true
      - icon: mdi:check
        label: Mark bins ready
        action: input_boolean.turn_on
        target:
          entity_id: input_boolean.bins_ready
```
