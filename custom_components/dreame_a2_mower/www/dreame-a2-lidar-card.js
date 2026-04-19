// Dreame A2 LiDAR Card — pure-WebGL point-cloud viewer with optional
// 2D-map underlay and live splat-size slider.
//
// Consumes the `.pcd` at /api/dreame_a2_mower/lidar/latest.pcd, renders
// with `gl.POINTS` and an orbit camera. Optionally textures a quad at
// Z=0 from the base-map PNG (`camera.dreame_a2_mower_map`) so the lawn
// shows under the 3D points. No external libraries — raw WebGL 1.0
// with ~40 LOC of mat4 helpers + ~30 LOC PCD parser.
//
// Usage (Lovelace YAML):
//   - url: /dreame_a2_mower/dreame-a2-lidar-card.js
//     type: module
//   cards:
//     - type: custom:dreame-a2-lidar-card
//       # All optional:
//       # point_size: 3            (default 2.5; live slider overrides)
//       # background: '#111'       (default black)
//       # url: /api/dreame_a2_mower/lidar/latest.pcd
//       # show_map: true           (default false)
//       # map_entity: camera.dreame_a2_mower_map
//
// Controls: drag to orbit, wheel to zoom. Bottom controls: slider for
// splat size (1-12 px), toggle for map underlay.
//
// Feasibility write-up: docs/research/webgl-lidar-card-feasibility.md

const VERTEX_SRC = `
  attribute vec3 aPos;
  attribute vec4 aColor;
  uniform mat4 uMVP;
  uniform float uPointSize;
  varying vec4 vColor;
  void main() {
    gl_Position = uMVP * vec4(aPos, 1.0);
    // Direct pixel size — no distance attenuation. Clip-space w at
    // default zoom is ~O(scene radius), which made previous
    // uPointSize / w formula clamp to the minimum 1 px regardless of
    // slider value. Plain uPointSize matches what the slider's
    // numeric readout promises.
    gl_PointSize = clamp(uPointSize, 1.0, 48.0);
    // PCL packs rgb as 0x00RRGGBB. Little-endian memory layout is
    // [B, G, R, 0]; WebGL reads that as (B, G, R, 0). Swizzle to RGB.
    vColor = vec4(aColor.b, aColor.g, aColor.r, 1.0);
  }
`;

const FRAGMENT_SRC = `
  precision mediump float;
  varying vec4 vColor;
  void main() {
    vec2 d = gl_PointCoord - vec2(0.5);
    if (dot(d, d) > 0.25) discard;
    gl_FragColor = vColor;
  }
`;

// --- Textured-quad shaders for the optional map underlay ---
const QUAD_VERTEX_SRC = `
  attribute vec3 aPos;
  attribute vec2 aUV;
  uniform mat4 uMVP;
  varying vec2 vUV;
  void main() {
    gl_Position = uMVP * vec4(aPos, 1.0);
    vUV = aUV;
  }
`;

const QUAD_FRAGMENT_SRC = `
  precision mediump float;
  varying vec2 vUV;
  uniform sampler2D uTex;
  uniform float uAlpha;
  void main() {
    vec4 c = texture2D(uTex, vUV);
    // Premultiply alpha against user-configurable transparency so the
    // underlay can be dimmed for better readability through the cloud.
    gl_FragColor = vec4(c.rgb, c.a * uAlpha);
  }
`;

// --------------- mat4 helpers ---------------

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
  const zl = Math.hypot(zx, zy, zz);
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

function compileShader(gl, type, src) {
  const s = gl.createShader(type);
  gl.shaderSource(s, src);
  gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
    throw new Error("shader compile: " + gl.getShaderInfoLog(s));
  }
  return s;
}

function linkProgram(gl, vs, fs) {
  const p = gl.createProgram();
  gl.attachShader(p, vs);
  gl.attachShader(p, fs);
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) {
    throw new Error("program link: " + gl.getProgramInfoLog(p));
  }
  return p;
}

// --------------- PCD parser ---------------

function parsePCD(buffer) {
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
  const bpp = hasRGB ? 16 : 12;
  if (buffer.byteLength < bodyOffset + points * bpp) {
    throw new Error(`PCD truncated: body short`);
  }
  return { points, bpp, bodyOffset, hasRGB };
}

function computeStats(buffer, bodyOffset, bpp, n) {
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
    this._gl = null;
    this._pointProgram = null;
    this._quadProgram = null;
    this._pointVBO = null;
    this._quadVBO = null;
    this._mapTex = null;
    this._mapTexReady = false;
    this._mapQuadWorld = null; // [[x0,y0],[x1,y1]] in world metres
    this._nPoints = 0;
    this._centroid = [0, 0, 0];
    this._radius = 1;
    this._pointSize = 2.5;
    this._showMap = false;
    this._mapAlpha = 0.85;
    this._yaw = Math.PI / 4;
    this._pitch = Math.PI / 4;
    this._distance = 0;
    this._dragging = false;
    this._lastX = 0;
    this._lastY = 0;
    this._dpr = window.devicePixelRatio || 1;
  }

  setConfig(config) {
    this._config = config || {};
    this._pointSize = Number(this._config.point_size ?? 2.5);
    this._showMap = Boolean(this._config.show_map ?? false);
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
        .controls {
          position: absolute; top: 8px; left: 8px; display: flex; flex-direction: column; gap: 6px;
          background: rgba(20, 20, 20, 0.55); padding: 6px 10px; border-radius: 8px;
          font-family: var(--primary-font-family, sans-serif); font-size: 12px; color: #ddd;
          backdrop-filter: blur(2px);
        }
        .controls label { display: flex; align-items: center; gap: 8px; white-space: nowrap; }
        .controls input[type=range] { width: 110px; }
        .controls input[type=checkbox] { margin: 0; }
      </style>
      <ha-card>
        <div class="wrap">
          <canvas></canvas>
          <div class="controls">
            <label>Splat
              <input type="range" class="splat" min="1" max="12" step="0.5" value="${this._pointSize}">
              <span class="splat-val">${this._pointSize}</span>
            </label>
            <label>
              <input type="checkbox" class="showmap" ${this._showMap ? "checked" : ""}>
              Map underlay
            </label>
          </div>
          <div class="status">Loading…</div>
          <div class="hint"></div>
        </div>
      </ha-card>
    `;
    this._canvas = this.shadowRoot.querySelector("canvas");
    this._status = this.shadowRoot.querySelector(".status");
    this._hint = this.shadowRoot.querySelector(".hint");
    this._splat = this.shadowRoot.querySelector(".splat");
    this._splatVal = this.shadowRoot.querySelector(".splat-val");
    this._showMapCb = this.shadowRoot.querySelector(".showmap");
    this._bindInput();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._loaded) this._fetchAndRender();
  }

  getCardSize() { return 6; }

  async _fetchAndRender() {
    if (!this._hass) return;
    this._loaded = true;
    try {
      const token = this._hass.auth?.data?.access_token;
      if (!token) throw new Error("No HA access token");
      const url = this._config.url || "/api/dreame_a2_mower/lidar/latest.pcd";
      this._setStatus("Fetching point cloud…");
      const r = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const buf = await r.arrayBuffer();
      this._setStatus("Parsing…");
      const meta = parsePCD(buf);
      this._nPoints = meta.points;
      const stats = computeStats(buf, meta.bodyOffset, meta.bpp, meta.points);
      this._centroid = stats.centroid;
      this._radius = Math.max(stats.radius, 1);
      this._bbox = stats.bbox;
      this._distance = this._radius * 2.5;
      this._hint.textContent = `${meta.points.toLocaleString()} pts · r=${this._radius.toFixed(1)}m`;
      this._setStatus("");
      this._initGL(buf, meta);
      if (this._showMap) await this._loadMapUnderlay();
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
    const gl = this._canvas.getContext("webgl", { antialias: true, premultipliedAlpha: true });
    if (!gl) throw new Error("WebGL not available");
    this._gl = gl;
    gl.clearColor(0, 0, 0, 0);
    gl.enable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

    // Point-cloud program
    const pVs = compileShader(gl, gl.VERTEX_SHADER, VERTEX_SRC);
    const pFs = compileShader(gl, gl.FRAGMENT_SHADER, FRAGMENT_SRC);
    this._pointProgram = linkProgram(gl, pVs, pFs);
    const body = new Uint8Array(buffer, meta.bodyOffset, meta.points * meta.bpp);
    this._pointVBO = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this._pointVBO);
    gl.bufferData(gl.ARRAY_BUFFER, body, gl.STATIC_DRAW);
    this._pointLocs = {
      aPos: gl.getAttribLocation(this._pointProgram, "aPos"),
      aColor: gl.getAttribLocation(this._pointProgram, "aColor"),
      uMVP: gl.getUniformLocation(this._pointProgram, "uMVP"),
      uPointSize: gl.getUniformLocation(this._pointProgram, "uPointSize"),
    };
    this._pointBPP = meta.bpp;
    this._pointHasRGB = meta.hasRGB;

    // Quad program (for map underlay)
    const qVs = compileShader(gl, gl.VERTEX_SHADER, QUAD_VERTEX_SRC);
    const qFs = compileShader(gl, gl.FRAGMENT_SHADER, QUAD_FRAGMENT_SRC);
    this._quadProgram = linkProgram(gl, qVs, qFs);
    this._quadLocs = {
      aPos: gl.getAttribLocation(this._quadProgram, "aPos"),
      aUV: gl.getAttribLocation(this._quadProgram, "aUV"),
      uMVP: gl.getUniformLocation(this._quadProgram, "uMVP"),
      uTex: gl.getUniformLocation(this._quadProgram, "uTex"),
      uAlpha: gl.getUniformLocation(this._quadProgram, "uAlpha"),
    };
  }

  async _loadMapUnderlay() {
    try {
      const entityId = this._config.map_entity || "camera.dreame_a2_mower_map";
      const state = this._hass.states?.[entityId];
      if (!state) throw new Error(`${entityId} not found`);
      const calib = state.attributes?.calibration_points;
      const token = this._hass.auth?.data?.access_token;
      if (!calib || calib.length < 3) {
        console.warn("[dreame-a2-lidar-card] no calibration_points on", entityId);
        return;
      }

      // Fetch the PNG and capture its pixel dimensions so we can turn
      // the four image corners into world-metre quad corners.
      const mapUrl = `/api/camera_proxy/${entityId}?token=${state.attributes?.access_token || ""}`;
      const r = await fetch(mapUrl, { headers: { Authorization: `Bearer ${token}` } });
      if (!r.ok) throw new Error(`map HTTP ${r.status}`);
      const blob = await r.blob();
      const bmp = await createImageBitmap(blob);

      const gl = this._gl;
      const tex = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, bmp);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      this._mapTex = tex;

      // calibration_points: list of 3 entries `{mower:{x,y}, map:{x,y}}`.
      // `mower.*` is mower-frame mm (includes all the
      // reflections/rotations the base renderer applied); `map.*` is
      // pixels in the served PNG. Fit the affine mower_mm → pixel:
      //   px = a*x + b*y + tx
      //   py = c*x + d*y + ty
      // then invert to pixel → mower_mm, and transform the 4 PNG
      // corners to get the quad's world coords.
      const [p0, p1, p2] = calib;
      const x0 = p0.mower.x, y0 = p0.mower.y;
      const x1 = p1.mower.x, y1 = p1.mower.y;
      const x2 = p2.mower.x, y2 = p2.mower.y;
      const u0 = p0.map.x, v0 = p0.map.y;
      const u1 = p1.map.x, v1 = p1.map.y;
      const u2 = p2.map.x, v2 = p2.map.y;
      const det = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0);
      if (Math.abs(det) < 1e-9) throw new Error("calib colinear");
      const a = ((u1 - u0) * (y2 - y0) - (u2 - u0) * (y1 - y0)) / det;
      const b = ((x1 - x0) * (u2 - u0) - (x2 - x0) * (u1 - u0)) / det;
      const c = ((v1 - v0) * (y2 - y0) - (v2 - v0) * (y1 - y0)) / det;
      const d = ((x1 - x0) * (v2 - v0) - (x2 - x0) * (v1 - v0)) / det;
      const tx = u0 - a * x0 - b * y0;
      const ty = v0 - c * x0 - d * y0;
      // Invert the 2x2 to get pixel → mower_mm
      const idet = 1 / (a * d - b * c);
      const inv_a = d * idet, inv_b = -b * idet;
      const inv_c = -c * idet, inv_d = a * idet;
      const px2mm = (px, py) => {
        const ox = px - tx, oy = py - ty;
        return [inv_a * ox + inv_b * oy, inv_c * ox + inv_d * oy];
      };

      const W = bmp.width, H = bmp.height;
      // Quad corners (world metres): translate pixel corners through
      // the inverse affine and divide by 1000 (mm → m).
      const cornersPx = [[0, 0], [W, 0], [W, H], [0, H]];
      const cornersM = cornersPx.map(([px, py]) => {
        const [mmx, mmy] = px2mm(px, py);
        return [mmx / 1000, mmy / 1000];
      });

      // Place the quad at the ground Z from the point-cloud bbox,
      // not Z=0 — the A2's ground level sits ~1 m below zero in our
      // captured PCDs, which made the quad appear floating above the
      // lawn dots.
      const groundZ = this._bbox ? this._bbox[0][2] : 0;

      // Two triangles; UVs 0-1 across the PNG (flip V so image-row-0
      // lands on the first corner which maps pixel (0, 0)).
      const [Atl, Atr, Abr, Abl] = cornersM;
      const data = new Float32Array([
        Atl[0], Atl[1], groundZ, 0, 0,
        Atr[0], Atr[1], groundZ, 1, 0,
        Abr[0], Abr[1], groundZ, 1, 1,
        Atl[0], Atl[1], groundZ, 0, 0,
        Abr[0], Abr[1], groundZ, 1, 1,
        Abl[0], Abl[1], groundZ, 0, 1,
      ]);
      this._quadVBO = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, this._quadVBO);
      gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
      this._mapTexReady = true;
    } catch (ex) {
      console.warn("[dreame-a2-lidar-card] map underlay failed:", ex);
      this._showMap = false;
      if (this._showMapCb) this._showMapCb.checked = false;
    }
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

    this._splat.addEventListener("input", () => {
      this._pointSize = parseFloat(this._splat.value);
      this._splatVal.textContent = this._pointSize;
    });

    this._showMapCb.addEventListener("change", async () => {
      this._showMap = this._showMapCb.checked;
      if (this._showMap && !this._mapTexReady && this._gl) {
        await this._loadMapUnderlay();
      }
    });
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

    // Draw map underlay first so point cloud depth-tests over it.
    if (this._showMap && this._mapTexReady && this._quadVBO) {
      gl.useProgram(this._quadProgram);
      gl.bindBuffer(gl.ARRAY_BUFFER, this._quadVBO);
      const stride = 5 * 4;
      gl.enableVertexAttribArray(this._quadLocs.aPos);
      gl.vertexAttribPointer(this._quadLocs.aPos, 3, gl.FLOAT, false, stride, 0);
      gl.enableVertexAttribArray(this._quadLocs.aUV);
      gl.vertexAttribPointer(this._quadLocs.aUV, 2, gl.FLOAT, false, stride, 12);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, this._mapTex);
      gl.uniform1i(this._quadLocs.uTex, 0);
      gl.uniform1f(this._quadLocs.uAlpha, this._mapAlpha);
      gl.uniformMatrix4fv(this._quadLocs.uMVP, false, mvp);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
      gl.disableVertexAttribArray(this._quadLocs.aUV);
    }

    // Points on top (depth test keeps roof points above ground points).
    gl.useProgram(this._pointProgram);
    gl.bindBuffer(gl.ARRAY_BUFFER, this._pointVBO);
    gl.enableVertexAttribArray(this._pointLocs.aPos);
    gl.vertexAttribPointer(this._pointLocs.aPos, 3, gl.FLOAT, false, this._pointBPP, 0);
    if (this._pointHasRGB) {
      gl.enableVertexAttribArray(this._pointLocs.aColor);
      gl.vertexAttribPointer(this._pointLocs.aColor, 4, gl.UNSIGNED_BYTE, true, this._pointBPP, 12);
    }
    gl.uniformMatrix4fv(this._pointLocs.uMVP, false, mvp);
    gl.uniform1f(this._pointLocs.uPointSize, this._pointSize * this._dpr);
    gl.drawArrays(gl.POINTS, 0, this._nPoints);
  }
}

customElements.define("dreame-a2-lidar-card", DreameA2LidarCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "dreame-a2-lidar-card",
  name: "Dreame A2 LiDAR Card",
  description: "Interactive WebGL 3D view of the mower's LiDAR point-cloud scan.",
});
