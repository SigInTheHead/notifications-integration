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
    this._load();
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
      .add-topic { display: flex; gap: 12px; align-items: center; }
      .add-topic ha-textfield { flex: 1; }
      .topics { display: grid; gap: 10px; }
      .topic { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 12px; align-items: center; }
      .topic ha-form { min-width: 0; margin: 0 !important; }
      .actions { display: flex; gap: 8px; align-self: center; align-items: center; transform: translateY(-14px); }
      button { border: 0; border-radius: 18px; padding: 9px 16px; font: inherit; color: var(--text-primary-color); background: var(--primary-color); cursor: pointer; }
      button.secondary { color: var(--primary-text-color); background: var(--secondary-background-color); }
      button.icon { display: grid; place-items: center; width: 36px; height: 36px; padding: 0; color: var(--secondary-text-color); background: transparent; }
      button.icon:hover { color: var(--error-color); background: var(--secondary-background-color); }
      button.icon ha-icon { --mdc-icon-size: 20px; }
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
      <h2>Topics</h2>
      <div class="description">Topics control which notifications a dashboard card can show. Removing a topic also removes its active notifications.</div>
      <div class="add-topic"><ha-textfield id="new-topic" label="Topic name"></ha-textfield><button id="add-topic">Add topic</button></div>
      <div class="topics" id="topics"></div>
    </ha-card>`;
    if (!this._settings) return;
    this._renderColorForm();
    this._renderTopics();
    this._root.querySelector("#add-topic").addEventListener("click", () => this._addTopic());
    this._root.querySelector("#new-topic").addEventListener("keydown", (event) => {
      if (event.key === "Enter") this._addTopic();
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
    if (!this._settings.topics.length) {
      container.innerHTML = '<div class="empty">No topics have been created.</div>';
      return;
    }
    for (const topic of this._settings.topics) {
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
      const save = this._button("Save", "secondary", () => this._renameTopic(topic.id, data));
      const remove = this._iconButton("mdi:delete-outline", "Remove topic", () => this._removeTopic(topic.id, topic.name));
      actions.append(save, remove);
      row.append(form, actions);
      container.appendChild(row);
    }
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

  async _addTopic() {
    const input = this._root.querySelector("#new-topic");
    await this._call(`${DOMAIN}/settings/add_topic`, { name: input.value });
  }

  async _renameTopic(id, data) {
    await this._call(`${DOMAIN}/settings/rename_topic`, { id, ...data });
  }

  async _removeTopic(id, name) {
    if (!window.confirm(`Remove “${name}”? Active notifications in this topic will also be removed.`)) return;
    await this._call(`${DOMAIN}/settings/remove_topic`, { id });
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
