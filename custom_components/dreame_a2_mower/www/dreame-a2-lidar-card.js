// Dreame A2 LiDAR Card — minimal pure-WebGL point-cloud viewer.
//
// Consumes the `.pcd` blob served at /api/dreame_a2_mower/lidar/latest.pcd,
// renders with `gl.POINTS` and an orbit camera. No external libraries —
// everything from raw WebGL 1.0 + a few lines of mat4 math so the install
// is a single-file drop.
//
// Usage (Lovelace YAML):
//   - url: /dreame_a2_mower/dreame-a2-lidar-card.js
//     type: module
//   cards:
//     - type: custom:dreame-a2-lidar-card
//       # All optional:
//       # point_size: 3          (default 2.5)
//       # background: '#111'     (default black)
//       # url: /api/dreame_a2_mower/lidar/latest.pcd
//
// Controls: drag to orbit, wheel to zoom.
//
// Feasibility write-up for architecture notes:
//   docs/research/webgl-lidar-card-feasibility.md

const VERTEX_SRC = `
  attribute vec3 aPos;
  attribute vec4 aColor;
  uniform mat4 uMVP;
  uniform float uPointSize;
  varying vec4 vColor;
  void main() {
    gl_Position = uMVP * vec4(aPos, 1.0);
    // Distance-attenuated point size. Clamp so it stays visible at all
    // zoom levels. gl_Position.w is ~distance-to-eye after projection.
    gl_PointSize = clamp(uPointSize / max(gl_Position.w, 0.1), 1.0, 24.0);
    // PCL packs rgb as 0x00RRGGBB. Little-endian byte order in the VBO
    // is [B, G, R, 0]; WebGL reads that into aColor as (B, G, R, 0).
    // Swizzle back to RGB.
    vColor = vec4(aColor.b, aColor.g, aColor.r, 1.0);
  }
`;

const FRAGMENT_SRC = `
  precision mediump float;
  varying vec4 vColor;
  void main() {
    // Round splat: discard fragments outside a circle inscribed in the
    // point's sprite bbox. No anti-aliasing — GL_POINTS smoothing is
    // unreliable across drivers.
    vec2 d = gl_PointCoord - vec2(0.5);
    if (dot(d, d) > 0.25) discard;
    gl_FragColor = vColor;
  }
`;

// --------------- mat4 helpers (inline, ~column-major like OpenGL) ---------------

function mat4Identity() {
  const m = new Float32Array(16);
  m[0] = m[5] = m[10] = m[15] = 1;
  return m;
}

function mat4Perspective(fovy, aspect, near, far) {
  const f = 1 / Math.tan(fovy / 2);
  const nf = 1 / (near - far);
  const m = new Float32Array(16);
  m[0] = f / aspect; m[5] = f;
  m[10] = (far + near) * nf; m[11] = -1;
  m[14] = 2 * far * near * nf;
  return m;
}

function mat4LookAt(eye, target, up) {
  const [ex, ey, ez] = eye;
  const [tx, ty, tz] = target;
  let zx = ex - tx, zy = ey - ty, zz = ez - tz;
  let zl = Math.hypot(zx, zy, zz);
  zx /= zl; zy /= zl; zz /= zl;
  let xx = up[1] * zz - up[2] * zy;
  let xy = up[2] * zx - up[0] * zz;
  let xz = up[0] * zy - up[1] * zx;
  const xl = Math.hypot(xx, xy, xz);
  xx /= xl; xy /= xl; xz /= xl;
  const yx = zy * xz - zz * xy;
  const yy = zz * xx - zx * xz;
  const yz = zx * xy - zy * xx;
  const m = new Float32Array(16);
  m[0] = xx; m[1] = yx; m[2] = zx; m[3] = 0;
  m[4] = xy; m[5] = yy; m[6] = zy; m[7] = 0;
  m[8] = xz; m[9] = yz; m[10] = zz; m[11] = 0;
  m[12] = -(xx * ex + xy * ey + xz * ez);
  m[13] = -(yx * ex + yy * ey + yz * ez);
  m[14] = -(zx * ex + zy * ey + zz * ez);
  m[15] = 1;
  return m;
}

function mat4Multiply(a, b) {
  const out = new Float32Array(16);
  for (let i = 0; i < 4; i++) {
    for (let j = 0; j < 4; j++) {
      let s = 0;
      for (let k = 0; k < 4; k++) s += a[k * 4 + j] * b[i * 4 + k];
      out[i * 4 + j] = s;
    }
  }
  return out;
}

// --------------- PCD parser ---------------

function parsePCD(buffer) {
  // Header is ASCII, terminated by first newline AFTER "DATA binary".
  // Read up to 1KB as ASCII to find the header end.
  const headerBytes = new Uint8Array(buffer, 0, Math.min(1024, buffer.byteLength));
  const headerText = new TextDecoder("ascii").decode(headerBytes);
  const dataIdx = headerText.indexOf("DATA binary");
  if (dataIdx < 0) throw new Error("Unsupported PCD: need DATA binary");
  const nl = headerText.indexOf("\n", dataIdx);
  const bodyOffset = nl + 1;
  const pointsMatch = headerText.match(/\nPOINTS\s+(\d+)/);
  if (!pointsMatch) throw new Error("PCD header missing POINTS");
  const points = parseInt(pointsMatch[1], 10);
  const fieldsMatch = headerText.match(/\nFIELDS\s+([^\n]+)/);
  const fields = fieldsMatch ? fieldsMatch[1].trim().split(/\s+/) : [];
  const hasRGB = fields.indexOf("rgb") >= 0;
  // For the g2408 firmware's PCD the layout is always 3×f32 xyz + u32 rgb
  // = 16 bytes per point. Rejecting anything else for now.
  const bpp = hasRGB ? 16 : 12;
  const expected = points * bpp;
  if (buffer.byteLength < bodyOffset + expected) {
    throw new Error(`PCD truncated: have ${buffer.byteLength - bodyOffset} body bytes, need ${expected}`);
  }
  return { points, bpp, bodyOffset, hasRGB };
}

function computeCentroidAndExtent(buffer, bodyOffset, bpp, n) {
  const view = new DataView(buffer);
  let sx = 0, sy = 0, sz = 0;
  let minx = Infinity, maxx = -Infinity;
  let miny = Infinity, maxy = -Infinity;
  let minz = Infinity, maxz = -Infinity;
  for (let i = 0; i < n; i++) {
    const o = bodyOffset + i * bpp;
    const x = view.getFloat32(o, true);
    const y = view.getFloat32(o + 4, true);
    const z = view.getFloat32(o + 8, true);
    sx += x; sy += y; sz += z;
    if (x < minx) minx = x; if (x > maxx) maxx = x;
    if (y < miny) miny = y; if (y > maxy) maxy = y;
    if (z < minz) minz = z; if (z > maxz) maxz = z;
  }
  return {
    centroid: [sx / n, sy / n, sz / n],
    bbox: [[minx, miny, minz], [maxx, maxy, maxz]],
    radius: Math.max(maxx - minx, maxy - miny, maxz - minz) / 2,
  };
}

// --------------- Card element ---------------

class DreameA2LidarCard extends HTMLElement {
  constructor() {
    super();
    this._config = null;
    this._hass = null;
    this._loaded = false;
    this._url = null;
    this._gl = null;
    this._program = null;
    this._vbo = null;
    this._nPoints = 0;
    this._centroid = [0, 0, 0];
    this._radius = 1;
    // Orbit-camera state
    this._yaw = Math.PI / 4;
    this._pitch = Math.PI / 4;
    this._distance = 0; // set after parse
    // Interaction state
    this._dragging = false;
    this._lastX = 0;
    this._lastY = 0;
    this._dpr = window.devicePixelRatio || 1;
  }

  setConfig(config) {
    this._config = config || {};
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        .wrap { position: relative; width: 100%; aspect-ratio: 1 / 1; background: ${this._config.background || "#111"}; border-radius: var(--ha-card-border-radius, 12px); overflow: hidden; }
        canvas { width: 100%; height: 100%; display: block; touch-action: none; cursor: grab; }
        canvas:active { cursor: grabbing; }
        .status { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: #bbb; font-family: var(--primary-font-family, sans-serif); font-size: 14px; pointer-events: none; }
        .status.err { color: #f88; }
        .hint { position: absolute; bottom: 8px; right: 10px; font-size: 11px; color: #888; font-family: monospace; pointer-events: none; }
      </style>
      <ha-card>
        <div class="wrap">
          <canvas></canvas>
          <div class="status">Loading…</div>
          <div class="hint"></div>
        </div>
      </ha-card>
    `;
    this._canvas = this.shadowRoot.querySelector("canvas");
    this._status = this.shadowRoot.querySelector(".status");
    this._hint = this.shadowRoot.querySelector(".hint");
    this._bindInput();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._loaded) this._fetchAndRender();
  }

  getCardSize() {
    return 6;
  }

  _url_from_config() {
    return this._config && this._config.url ? this._config.url : "/api/dreame_a2_mower/lidar/latest.pcd";
  }

  async _fetchAndRender() {
    if (!this._hass) return;
    this._loaded = true; // once-only; future fetches driven by hass entity listener
    const url = this._url_from_config();
    try {
      const token = this._hass.auth?.data?.access_token;
      if (!token) throw new Error("No HA access token");
      this._setStatus("Fetching point cloud…");
      const r = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const buf = await r.arrayBuffer();
      this._setStatus("Parsing…");
      const meta = parsePCD(buf);
      this._nPoints = meta.points;
      const stats = computeCentroidAndExtent(buf, meta.bodyOffset, meta.bpp, meta.points);
      this._centroid = stats.centroid;
      this._radius = Math.max(stats.radius, 1);
      this._distance = this._radius * 2.5;
      this._hint.textContent = `${meta.points.toLocaleString()} pts · r=${this._radius.toFixed(1)}m`;
      this._setStatus("");
      this._initGL(buf, meta);
      this._startRenderLoop();
    } catch (ex) {
      console.error("[dreame-a2-lidar-card]", ex);
      this._setStatus(`Error: ${ex.message}`, true);
    }
  }

  _setStatus(msg, isError = false) {
    this._status.textContent = msg;
    this._status.classList.toggle("err", isError);
    this._status.style.display = msg ? "flex" : "none";
  }

  _initGL(buffer, meta) {
    const gl = this._canvas.getContext("webgl", { antialias: true });
    if (!gl) throw new Error("WebGL not available");
    this._gl = gl;
    gl.clearColor(0, 0, 0, 1);
    gl.enable(gl.DEPTH_TEST);

    const vs = gl.createShader(gl.VERTEX_SHADER);
    gl.shaderSource(vs, VERTEX_SRC);
    gl.compileShader(vs);
    if (!gl.getShaderParameter(vs, gl.COMPILE_STATUS)) {
      throw new Error("VS compile: " + gl.getShaderInfoLog(vs));
    }
    const fs = gl.createShader(gl.FRAGMENT_SHADER);
    gl.shaderSource(fs, FRAGMENT_SRC);
    gl.compileShader(fs);
    if (!gl.getShaderParameter(fs, gl.COMPILE_STATUS)) {
      throw new Error("FS compile: " + gl.getShaderInfoLog(fs));
    }
    const prog = gl.createProgram();
    gl.attachShader(prog, vs);
    gl.attachShader(prog, fs);
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
      throw new Error("Program link: " + gl.getProgramInfoLog(prog));
    }
    gl.useProgram(prog);
    this._program = prog;

    // Upload the PCD body directly — 16 bytes per point (xyz float32 + rgb uint32).
    const body = new Uint8Array(buffer, meta.bodyOffset, meta.points * meta.bpp);
    this._vbo = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this._vbo);
    gl.bufferData(gl.ARRAY_BUFFER, body, gl.STATIC_DRAW);

    const aPos = gl.getAttribLocation(prog, "aPos");
    gl.enableVertexAttribArray(aPos);
    gl.vertexAttribPointer(aPos, 3, gl.FLOAT, false, meta.bpp, 0);

    if (meta.hasRGB) {
      const aColor = gl.getAttribLocation(prog, "aColor");
      gl.enableVertexAttribArray(aColor);
      gl.vertexAttribPointer(aColor, 4, gl.UNSIGNED_BYTE, true, meta.bpp, 12);
    }

    this._uMVP = gl.getUniformLocation(prog, "uMVP");
    this._uPointSize = gl.getUniformLocation(prog, "uPointSize");
  }

  _bindInput() {
    this._canvas.addEventListener("mousedown", (e) => {
      this._dragging = true;
      this._lastX = e.clientX;
      this._lastY = e.clientY;
    });
    window.addEventListener("mouseup", () => { this._dragging = false; });
    window.addEventListener("mousemove", (e) => {
      if (!this._dragging) return;
      const dx = e.clientX - this._lastX;
      const dy = e.clientY - this._lastY;
      this._lastX = e.clientX;
      this._lastY = e.clientY;
      this._yaw -= dx * 0.01;
      this._pitch -= dy * 0.01;
      this._pitch = Math.max(-Math.PI / 2 + 0.05, Math.min(Math.PI / 2 - 0.05, this._pitch));
    });
    this._canvas.addEventListener("wheel", (e) => {
      e.preventDefault();
      const f = Math.exp(e.deltaY * 0.001);
      this._distance = Math.min(this._radius * 8, Math.max(this._radius * 0.2, this._distance * f));
    }, { passive: false });
  }

  _startRenderLoop() {
    let lastResize = 0;
    const tick = () => {
      if (!this.isConnected) return;
      const now = performance.now();
      if (now - lastResize > 250) {
        this._resizeIfNeeded();
        lastResize = now;
      }
      this._draw();
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  _resizeIfNeeded() {
    const c = this._canvas;
    const w = (c.clientWidth * this._dpr) | 0;
    const h = (c.clientHeight * this._dpr) | 0;
    if (c.width !== w || c.height !== h) {
      c.width = w;
      c.height = h;
      this._gl.viewport(0, 0, w, h);
    }
  }

  _draw() {
    const gl = this._gl;
    if (!gl) return;
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

    const [cx, cy, cz] = this._centroid;
    const ex = cx + this._distance * Math.cos(this._pitch) * Math.cos(this._yaw);
    const ey = cy + this._distance * Math.cos(this._pitch) * Math.sin(this._yaw);
    const ez = cz + this._distance * Math.sin(this._pitch);
    const aspect = this._canvas.width / Math.max(this._canvas.height, 1);
    const proj = mat4Perspective(Math.PI / 3, aspect, 0.1, this._radius * 40);
    const view = mat4LookAt([ex, ey, ez], this._centroid, [0, 0, 1]);
    const mvp = mat4Multiply(proj, view);
    gl.uniformMatrix4fv(this._uMVP, false, mvp);
    gl.uniform1f(this._uPointSize, (this._config.point_size || 2.5) * this._dpr);
    gl.drawArrays(gl.POINTS, 0, this._nPoints);
  }
}

customElements.define("dreame-a2-lidar-card", DreameA2LidarCard);

// Announce to Lovelace's custom-card picker so the user can add it via the UI.
window.customCards = window.customCards || [];
window.customCards.push({
  type: "dreame-a2-lidar-card",
  name: "Dreame A2 LiDAR Card",
  description: "Interactive WebGL 3D view of the mower's LiDAR point-cloud scan.",
});
