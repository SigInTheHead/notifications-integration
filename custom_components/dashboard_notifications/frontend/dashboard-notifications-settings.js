/* Dashboard Notifications integration settings panel. */
const DOMAIN = "dashboard_notifications";
const SEVERITIES = ["info", "success", "warning", "error"];

class DashboardNotificationsSettingsPanel extends HTMLElement {
  constructor() {
    super();
    this._root = this.attachShadow({ mode: "open" });
  }

  set hass(hass) {
    this._hass = hass;
    // Home Assistant assigns a new hass object for every state update. Reloading
    // here tears down open picker dialogs, so only load settings once per panel.
    if (!this._loaded) {
      this._loaded = true;
      this._load();
    }
  }

  async _load() {
    if (!this._hass) return;
    try {
      this._settings = await this._hass.callWS({ type: `${DOMAIN}/settings` });
      this._error = undefined;
    } catch (error) {
      this._error = error?.message || "Unable to load settings.";
    }
    this._render();
  }

  _render() {
    if (!this._hass) return;
    const error = this._error ? `<ha-alert alert-type="error">${this._escape(this._error)}</ha-alert>` : "";
    this._root.innerHTML = `<style>
      :host { display: block; max-width: 900px; margin: 0 auto; padding: 24px; box-sizing: border-box; }
      h1 { margin: 0 0 20px; font-size: 1.8rem; font-weight: 400; }
      h2 { margin: 0; font-size: 1.2rem; font-weight: 500; }
      ha-card { display: block; margin: 16px 0; padding: 20px; }
      .description { color: var(--secondary-text-color); margin: 8px 0 20px; }
      .topic-header { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
      .topics { display: grid; gap: 10px; }
      .topic { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 12px; align-items: center; }
      .topic ha-form { min-width: 0; margin: 0 !important; }
      .actions { display: flex; gap: 8px; align-self: center; align-items: center; transform: translateY(-14px); }
      button { border: 0; border-radius: 18px; padding: 9px 16px; font: inherit; color: var(--text-primary-color); background: var(--primary-color); cursor: pointer; }
      button.secondary { color: var(--primary-text-color); background: var(--secondary-background-color); }
      button.icon { display: grid; place-items: center; width: 44px; height: 44px; padding: 0; color: var(--secondary-text-color); background: transparent; }
      button.icon:hover { color: var(--error-color); background: var(--secondary-background-color); }
      button.icon ha-icon { --mdc-icon-size: 22px; }
      button:disabled { opacity: .5; cursor: default; }
      .empty { color: var(--secondary-text-color); font-style: italic; }
      ha-alert { margin-bottom: 16px; }
      @media (max-width: 600px) { :host { padding: 16px; } .topic { grid-template-columns: 1fr; } .actions { transform: none; } }
    </style>
    <h1>Dashboard Notifications</h1>${error}
    <ha-card>
      <h2>Severity colours</h2>
      <div class="description">These colours apply to every Dashboard Notifications card.</div>
      <div id="colors"></div>
    </ha-card>
    <ha-card>
      <div class="topic-header"><h2>Topics</h2><button id="add-topic">Add topic</button></div>
      <div class="description">Topics control which notifications a dashboard card can show. Removing a topic also removes its active notifications.</div>
      <div class="topics" id="topics"></div>
    </ha-card>`;
    if (!this._settings) return;
    this._renderColorForm();
    this._renderTopics();
    this._root.querySelector("#add-topic").addEventListener("click", () => {
      this._addingTopic = true;
      this._render();
    });
  }

  _renderColorForm() {
    const form = document.createElement("ha-form");
    form.hass = this._hass;
    form.data = this._settings.severity_colors;
    form.schema = SEVERITIES.map((severity) => ({
      name: severity,
      // Do not declare a selector default: choosing that colour would then
      // intentionally emit no value, making it impossible to save explicitly.
      selector: { ui_color: {} },
    }));
    form.computeLabel = (schema) => `${schema.name[0].toUpperCase()}${schema.name.slice(1)}`;
    form.addEventListener("value-changed", async (event) => {
      const colors = { ...this._settings.severity_colors, ...event.detail.value };
      await this._call(`${DOMAIN}/settings/set_colors`, { severity_colors: colors });
    });
    this._root.querySelector("#colors").appendChild(form);
  }

  _renderTopics() {
    const container = this._root.querySelector("#topics");
    if (this._addingTopic) {
      container.appendChild(this._topicRow({ name: "", icon: undefined, color: undefined }, true));
    }
    if (!this._settings.topics.length && !this._addingTopic) {
      container.innerHTML = '<div class="empty">No topics have been created.</div>';
      return;
    }
    for (const topic of this._settings.topics) {
      container.appendChild(this._topicRow(topic));
    }
  }

  _topicRow(topic, isNew = false) {
      const row = document.createElement("div");
      row.className = "topic";
      const form = document.createElement("ha-form");
      form.hass = this._hass;
      form.data = {
        name: topic.name,
        icon: topic.icon,
        color: topic.color,
      };
      form.schema = [{
        name: "",
        type: "grid",
        schema: [
          { name: "name", required: true, selector: { text: {} } },
          { name: "icon", selector: { icon: {} } },
          { name: "color", selector: { ui_color: { include_none: true } } },
        ],
      }];
      form.computeLabel = (schema) => ({ name: "Topic name", icon: "Default icon", color: "Default colour" })[schema.name];
      let data = { ...form.data };
      form.addEventListener("value-changed", (event) => { data = { ...data, ...event.detail.value }; });
      const actions = document.createElement("div");
      actions.className = "actions";
      actions.append(this._button("Save", "secondary", () => isNew ? this._createTopic(data) : this._renameTopic(topic.id, data)));
      if (isNew) {
        actions.append(this._iconButton("mdi:close", "Cancel adding topic", () => this._cancelNewTopic()));
      } else {
        actions.append(this._iconButton("mdi:delete-outline", "Remove topic", () => this._removeTopic(topic.id, topic.name)));
      }
      row.append(form, actions);
      return row;
  }

  _button(label, className, handler) {
    const button = document.createElement("button");
    button.textContent = label;
    button.className = className;
    button.addEventListener("click", handler);
    return button;
  }

  _iconButton(icon, label, handler) {
    const button = this._button("", "icon", handler);
    button.title = label;
    button.setAttribute("aria-label", label);
    button.innerHTML = `<ha-icon icon="${icon}"></ha-icon>`;
    return button;
  }

  async _createTopic(data) {
    await this._call(`${DOMAIN}/settings/add_topic`, data);
    if (!this._error) {
      this._addingTopic = false;
      this._render();
    }
  }

  _cancelNewTopic() {
    this._addingTopic = false;
    this._error = undefined;
    this._render();
  }

  async _renameTopic(id, data) {
    await this._call(`${DOMAIN}/settings/rename_topic`, { topic_id: id, ...data });
  }

  async _removeTopic(id, name) {
    const dialog = document.createElement("ha-dialog");
    dialog.hass = this._hass;
    dialog.setAttribute("header-title", "Remove topic?");
    dialog.innerHTML = `<div>Remove “${this._escape(name)}”? Its active notifications will also be removed.</div>`;
    const closeDialog = () => {
      dialog.open = false;
      dialog.remove();
    };

    const footer = document.createElement("ha-dialog-footer");
    footer.slot = "footer";
    const cancel = document.createElement("ha-button");
    cancel.slot = "secondaryAction";
    cancel.setAttribute("appearance", "plain");
    cancel.textContent = "Cancel";
    cancel.addEventListener("click", closeDialog);
    const remove = document.createElement("ha-button");
    remove.slot = "primaryAction";
    remove.setAttribute("variant", "danger");
    remove.textContent = "Remove";
    remove.addEventListener("click", async () => {
      closeDialog();
      await this._confirmRemoveTopic(id);
    });
    footer.append(cancel, remove);
    dialog.append(footer);
    this._root.append(dialog);
    dialog.open = true;
    dialog.addEventListener("closed", () => dialog.remove(), { once: true });
  }

  async _confirmRemoveTopic(id) {
    await this._call(`${DOMAIN}/settings/remove_topic`, { topic_id: id });
  }

  async _call(type, data) {
    try {
      this._settings = await this._hass.callWS({ type, ...data });
      this._error = undefined;
    } catch (error) {
      this._error = error?.message || "Unable to save settings.";
    }
    this._render();
  }

  _escape(value) {
    const node = document.createElement("span");
    node.textContent = String(value);
    return node.innerHTML;
  }
}

customElements.define("dashboard-notifications-settings-panel", DashboardNotificationsSettingsPanel);
