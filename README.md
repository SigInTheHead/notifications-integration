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
