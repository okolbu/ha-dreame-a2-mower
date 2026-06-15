// Generic multi-select card: reads `items` from a sensor attribute and calls a
// service with the checked item ids. Reusable across patrol points, patrol
// edges, and (later) zone/spot mow — set entity/service/id_param per instance.
class DreameMultiSelectCard extends HTMLElement {
  setConfig(config) {
    if (!config.entity) throw new Error("entity is required");
    if (!config.service) throw new Error("service is required (domain.service)");
    this._config = {
      items_attribute: "items",
      id_param: "ids",
      action_label: "Start",
      ...config,
    };
    this._checked = new Set();
    this._rendered = false;
  }

  set hass(hass) {
    this._hass = hass;
    this._update();
  }

  _items() {
    const st = this._hass && this._hass.states[this._config.entity];
    const attr = st && st.attributes[this._config.items_attribute];
    return Array.isArray(attr) ? attr : [];
  }

  _key(item) { return JSON.stringify(item.id); }

  _syncBtn() {
    const off = this._checked.size === 0;
    this._btn.disabled = off;
    this._btn.style.opacity = off ? "0.5" : "1";
    this._btn.style.cursor = off ? "default" : "pointer";
  }

  _update() {
    const items = this._items();
    if (!this._rendered) {
      this.innerHTML = `
        <ha-card header="${this._config.title || ""}">
          <div class="dms-list" style="padding:0 16px"></div>
          <div style="padding:16px">
            <button class="dms-go" style="background:var(--primary-color);color:var(--text-primary-color,#fff);border:none;padding:8px 18px;border-radius:6px;font-size:14px;font-weight:500"></button>
          </div>
        </ha-card>`;
      this._list = this.querySelector(".dms-list");
      this._btn = this.querySelector(".dms-go");
      this._btn.textContent = this._config.action_label;
      this._btn.addEventListener("click", () => this._fire());
      this._rendered = true;
    }
    const present = new Set(items.map((i) => this._key(i)));
    for (const k of [...this._checked]) if (!present.has(k)) this._checked.delete(k);
    this._list.innerHTML = "";
    for (const item of items) {
      const k = this._key(item);
      const row = document.createElement("label");
      row.style.cssText = "display:flex;align-items:center;gap:8px;padding:4px 0;cursor:pointer";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = this._checked.has(k);
      cb.addEventListener("change", () => {
        if (cb.checked) this._checked.add(k); else this._checked.delete(k);
        this._syncBtn();
      });
      const span = document.createElement("span");
      let extra = "";
      if (item.cycles != null) extra += ` ×${item.cycles}`;
      if (item.auto_capture != null) extra += item.auto_capture ? " 📷" : "";
      span.textContent = (item.label || k) + extra;
      row.appendChild(cb);
      row.appendChild(span);
      this._list.appendChild(row);
    }
    if (items.length === 0) this._list.textContent = "No items.";
    this._syncBtn();
  }

  _fire() {
    const items = this._items();
    const ids = items.filter((i) => this._checked.has(this._key(i))).map((i) => i.id);
    if (ids.length === 0) return;
    const [domain, service] = this._config.service.split(".");
    const data = { [this._config.id_param]: ids };
    if (this._config.map_id != null) data.map_id = this._config.map_id;
    this._hass.callService(domain, service, data);
  }

  getCardSize() { return 3; }
}

if (!customElements.get("dreame-multi-select-card")) {
  customElements.define("dreame-multi-select-card", DreameMultiSelectCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "dreame-multi-select-card",
    name: "Dreame Multi-Select",
    description: "Pick items from a sensor's `items` attribute and call a service with the ids.",
  });
}

// Card version banner — lets the user confirm which build loaded in the
// browser console (the cards "cache hard"; a stale cache shows the old version).
const CARD_VERSION = "1.0.28a3";
console.info(
  `%c dreame-multi-select-card v${CARD_VERSION} `,
  "color:#fff;background:#2b8a3e;border-radius:3px;padding:1px 4px"
);
