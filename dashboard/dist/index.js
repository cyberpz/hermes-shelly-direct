/* Shelly Direct — Hermes dashboard tab.
 * Plain IIFE bundle: React.createElement only, no imports, no build step, no CDN.
 * Talks to the plugin backend at /api/plugins/shelly-direct via SDK.fetchJSON.
 */
(function () {
  "use strict";
  if (typeof window === "undefined") return;
  var SDK = window.__HERMES_PLUGIN_SDK__;
  var registry = window.__HERMES_PLUGINS__;
  if (!SDK || !SDK.React || typeof SDK.fetchJSON !== "function" ||
      !registry || typeof registry.register !== "function") return;

  var React = SDK.React;
  var h = React.createElement;
  var hooks = SDK.hooks || {};
  var useState = hooks.useState;
  var useEffect = hooks.useEffect;
  var useCallback = hooks.useCallback;
  var useRef = hooks.useRef;
  var C = SDK.components || {};
  var Card = C.Card, CardHeader = C.CardHeader, CardTitle = C.CardTitle, CardContent = C.CardContent;
  var Badge = C.Badge, Button = C.Button;
  var utils = SDK.utils || {};
  var cn = typeof utils.cn === "function" ? utils.cn : function () {
    return Array.prototype.slice.call(arguments).filter(Boolean).join(" ");
  };
  var _timeAgo = typeof utils.timeAgo === "function" ? utils.timeAgo : function (v) {
    return v ? String(v) : "never";
  };
  // SDK timeAgo expects epoch millis; accept ISO strings and numbers alike
  var timeAgo = function (v) {
    if (v == null) return "never";
    var ms = typeof v === "number" ? v : Date.parse(v);
    if (isNaN(ms)) return "never";
    return _timeAgo(ms);
  };

  var API = "/api/plugins/shelly-direct";
  var REFRESH_MS = 10000;

  /* ---------- helpers ---------- */

  function getJSON(path) { return SDK.fetchJSON(API + path); }
  function postJSON(path, body) {
    return SDK.fetchJSON(API + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {})
    });
  }
  function errMsg(e) {
    if (!e) return "request failed";
    if (typeof e === "string") return e;
    return String(e.message || e.error || "request failed");
  }
  function isNum(v) { return typeof v === "number" && isFinite(v); }
  function fmtEnergy(r) {
    var parts = [];
    if (r && isNum(r.apower)) parts.push(r.apower.toFixed(1) + " W");
    if (r && isNum(r.atotal)) parts.push((r.atotal / 1000).toFixed(2) + " kWh");
    return parts.join(" · ");
  }
  function channelsOfType(device, type) {
    var list = device && Array.isArray(device.channels) ? device.channels : [];
    return list.filter(function (c) { return c && c.type === type; });
  }
  /* Status wins; fall back to declared channels so controls appear before first poll. */
  function relaysOf(device, status) {
    if (status && Array.isArray(status.relays) && status.relays.length) return status.relays;
    return channelsOfType(device, "relay").map(function (c) { return { index: c.index, on: null, name: c.name }; });
  }
  function lightsOf(device, status) {
    if (status && Array.isArray(status.lights) && status.lights.length) return status.lights;
    return channelsOfType(device, "light").map(function (c) { return { index: c.index, on: null, name: c.name }; });
  }
  function coversOf(device, status) {
    if (status && Array.isArray(status.covers) && status.covers.length) return status.covers;
    return channelsOfType(device, "cover").map(function (c) { return { index: c.index, state: null, position: null }; });
  }

  /* ---------- small components ---------- */

  function BrightnessSlider(props) {
    var initial = isNum(props.value) ? props.value : 0;
    var pair = useState(initial);
    var val = pair[0], setVal = pair[1];
    var synced = useRef(initial);
    useEffect(function () {
      if (isNum(props.value) && props.value !== synced.current) {
        synced.current = props.value;
        setVal(props.value);
      }
    }, [props.value]);
    function commit() {
      if (props.disabled || val === synced.current) return;
      synced.current = val;
      if (props.onCommit) props.onCommit(val);
    }
    return h("input", {
      type: "range", min: 0, max: 100, value: val,
      disabled: !!props.disabled,
      className: "sd-slider",
      "aria-label": "Brightness",
      onChange: function (e) { setVal(Number(e.target.value)); },
      onMouseUp: commit,
      onTouchEnd: commit,
      onBlur: commit
    });
  }

  function DeviceCard(props) {
    var d = props.device;
    var status = props.status || null;
    var error = props.error;
    var pending = !!props.pending;
    var offline = !d.online;
    var disabled = offline || pending;
    var rows = [];

    var relays = relaysOf(d, status);
    relays.forEach(function (r, i) {
      var power = fmtEnergy(r);
      rows.push(h("div", { key: "r" + i, className: "flex items-center gap-2" },
        h(Button, {
          size: "sm", variant: r.on ? "default" : "outline", disabled: disabled,
          onClick: function () {
            props.act({ action: r.on == null ? "toggle" : (r.on ? "off" : "on"), channel: r.index });
          }
        }, r.on == null ? "Toggle" : (r.on ? "On" : "Off")),
        (r.name || relays.length > 1)
          ? h("span", { className: "text-xs text-muted-foreground truncate" }, r.name || ("Ch " + r.index))
          : null,
        power ? h("span", { className: "ml-auto font-mono text-xs text-muted-foreground whitespace-nowrap" }, power) : null
      ));
    });

    var lights = lightsOf(d, status);
    lights.forEach(function (l, i) {
      rows.push(h("div", { key: "l" + i, className: "flex items-center gap-2" },
        h(Button, {
          size: "sm", variant: l.on ? "default" : "outline", disabled: disabled,
          onClick: function () { props.act({ action: l.on ? "off" : "on", channel: l.index }); }
        }, l.on == null ? "Toggle" : (l.on ? "On" : "Off")),
        h(BrightnessSlider, {
          value: isNum(l.brightness) ? l.brightness : (l.on ? 100 : 0),
          disabled: disabled,
          onCommit: function (b) { props.act({ action: "set", brightness: b, channel: l.index }); }
        }),
        h("span", { className: "font-mono text-xs text-muted-foreground whitespace-nowrap" },
          isNum(l.brightness) ? l.brightness + "%" : (l.on == null ? "--" : "100%"))
      ));
    });

    var covers = coversOf(d, status);
    covers.forEach(function (cv, i) {
      var label = cv.state ? String(cv.state) : "--";
      if (isNum(cv.position)) label += " · " + Math.round(cv.position) + "%";
      rows.push(h("div", { key: "c" + i, className: "flex items-center gap-1" },
        h(Button, { size: "sm", variant: "outline", disabled: disabled,
          onClick: function () { props.act({ action: "cover", op: "open", channel: cv.index }); } }, "Open"),
        h(Button, { size: "sm", variant: "outline", disabled: disabled,
          onClick: function () { props.act({ action: "cover", op: "stop", channel: cv.index }); } }, "Stop"),
        h(Button, { size: "sm", variant: "outline", disabled: disabled,
          onClick: function () { props.act({ action: "cover", op: "close", channel: cv.index }); } }, "Close"),
        h("span", { className: "ml-auto text-xs text-muted-foreground whitespace-nowrap" }, label)
      ));
    });

    var s = status && status.sensors ? status.sensors : null;
    var chips = [];
    if (s) {
      if (isNum(s.temperature)) chips.push(s.temperature.toFixed(1) + " °C");
      if (isNum(s.humidity)) chips.push(Math.round(s.humidity) + " %RH");
      if (isNum(s.battery)) chips.push(Math.round(s.battery) + "% batt");
    }
    if (chips.length) {
      rows.push(h("div", { key: "s", className: "flex flex-wrap gap-1" },
        chips.map(function (t, i) {
          return h(Badge, { key: i, variant: "outline", className: "text-xs font-normal" }, t);
        })
      ));
    }

    var body;
    if (rows.length) body = rows;
    else if (offline) body = h("div", { className: "text-xs text-muted-foreground" },
      d.last_seen ? "Offline — last seen " + timeAgo(d.last_seen) : "Offline");
    else if (pending) body = h("div", { className: "text-xs text-muted-foreground" }, "Working…");
    else if (status) body = h("div", { className: "text-xs text-muted-foreground" }, "No controllable channels reported.");
    else body = h("div", { className: "text-xs text-muted-foreground" }, "Waiting for status…");

    return h(Card, { className: cn("sd-card", offline && "opacity-50") },
      h(CardHeader, { className: "pb-2 gap-1" },
        h("div", { className: "flex items-start justify-between gap-2" },
          h("div", { className: "min-w-0" },
            h(CardTitle, { className: "text-base truncate" }, d.name || d.id),
            d.model ? h("div", { className: "text-xs text-muted-foreground truncate" }, d.model) : null
          ),
          h("span", {
            className: cn("sd-dot", d.online ? "sd-dot-on" : "sd-dot-off"),
            title: d.online ? "online" : "offline"
          })
        ),
        h("div", { className: "flex flex-wrap items-center gap-1" },
          h(Badge, { variant: "secondary", className: "text-xs" }, "G" + (d.gen || "?")),
          h(Badge, { variant: "outline", className: "text-xs font-normal" }, d.kind || "device"),
          d.ip ? h("span", { className: "font-mono text-xs text-muted-foreground" }, d.ip) : null,
          pending ? h("span", { className: "sd-spin" }) : null,
          error ? h(Badge, { variant: "destructive", className: "sd-err text-xs" }, error) : null
        )
      ),
      h(CardContent, { className: "flex flex-col gap-2" }, body)
    );
  }

  /* ---------- main tab ---------- */

  function App() {
    var storePair = useState({ devices: [], statuses: {}, errors: {}, discovering: false, lastUpdate: null, loaded: false });
    var store = storePair[0], setStore = storePair[1];
    var pendPair = useState({});
    var pending = pendPair[0], setPendingMap = pendPair[1];
    var setPair = useState(null);
    var settings = setPair[0], setSettings = setPair[1];
    var verPair = useState("1.0.0");
    var version = verPair[0], setVersion = verPair[1];
    var fatalPair = useState("");
    var fatal = fatalPair[0], setFatal = fatalPair[1];
    var aliveRef = useRef(true);

    var patch = useCallback(function (p) {
      setStore(function (prev) {
        return Object.assign({}, prev, typeof p === "function" ? p(prev) : p);
      });
    }, []);

    var setPendingFor = useCallback(function (mac, on) {
      setPendingMap(function (prev) {
        var next = Object.assign({}, prev);
        if (on) next[mac] = true; else delete next[mac];
        return next;
      });
    }, []);

    var setDeviceStatus = useCallback(function (mac, st) {
      patch(function (prev) {
        var statuses = Object.assign({}, prev.statuses); statuses[mac] = st || {};
        var errors = Object.assign({}, prev.errors); delete errors[mac];
        return { statuses: statuses, errors: errors };
      });
    }, [patch]);

    var setDeviceError = useCallback(function (mac, msg) {
      patch(function (prev) {
        var errors = Object.assign({}, prev.errors); errors[mac] = msg;
        return { errors: errors };
      });
    }, [patch]);

    var fetchDevice = useCallback(function (mac) {
      return getJSON("/device/" + encodeURIComponent(mac)).then(function (res) {
        if (!aliveRef.current) return;
        if (res && res.ok === false) setDeviceError(mac, res.error || "device read failed");
        else if (res) setDeviceStatus(mac, res.status);
      }).catch(function (e) {
        if (aliveRef.current) setDeviceError(mac, errMsg(e));
      });
    }, [setDeviceStatus, setDeviceError]);

    var fetchStatuses = useCallback(function (devices) {
      (devices || []).forEach(function (d) {
        if (d && d.online && d.mac) fetchDevice(d.mac);
      });
    }, [fetchDevice]);

    var loadDevices = useCallback(function () {
      return getJSON("/devices").then(function (res) {
        if (!aliveRef.current) return;
        var devs = res && Array.isArray(res.devices) ? res.devices : [];
        patch({ devices: devs, lastUpdate: new Date().toISOString(), loaded: true });
        setFatal("");
        fetchStatuses(devs);
      }).catch(function (e) {
        if (aliveRef.current) { setFatal(errMsg(e)); patch({ loaded: true }); }
      });
    }, [patch, fetchStatuses]);

    var discover = useCallback(function () {
      patch({ discovering: true });
      return postJSON("/discover").then(function (res) {
        if (!aliveRef.current) return;
        var devs = res && Array.isArray(res.devices) ? res.devices : [];
        patch({ devices: devs, discovering: false, lastUpdate: new Date().toISOString(), loaded: true });
        setFatal("");
        fetchStatuses(devs);
      }).catch(function (e) {
        if (aliveRef.current) { patch({ discovering: false, loaded: true }); setFatal(errMsg(e)); }
      });
    }, [patch, fetchStatuses]);

    var act = useCallback(function (mac, payload) {
      setPendingFor(mac, true);
      postJSON("/action", Object.assign({ mac: mac }, payload)).then(function (res) {
        if (!res || res.ok === false) throw new Error((res && res.error) || "device rejected command");
        return fetchDevice(mac);
      }).catch(function (e) {
        if (aliveRef.current) setDeviceError(mac, errMsg(e));
      }).then(function () {
        if (aliveRef.current) setPendingFor(mac, false);
      });
    }, [setPendingFor, fetchDevice, setDeviceError]);

    useEffect(function () {
      aliveRef.current = true;
      getJSON("/health").then(function (r) {
        if (aliveRef.current && r && r.version) setVersion(String(r.version));
      }).catch(function () {});
      getJSON("/settings").then(function (r) {
        if (aliveRef.current && r && r.settings) setSettings(r.settings);
      }).catch(function () {});
      loadDevices();
      var iv = setInterval(loadDevices, REFRESH_MS);
      return function () {
        aliveRef.current = false;
        clearInterval(iv);
      };
    }, [loadDevices]);

    var devices = store.devices;
    var onlineCount = devices.filter(function (d) { return d.online; }).length;

    return h("div", { className: "sd-wrap flex flex-col gap-4 p-4" },
      h("div", { className: "flex flex-wrap items-center justify-between gap-3" },
        h("div", { className: "flex items-center gap-2" },
          h("h1", { className: "text-xl font-semibold tracking-tight" }, "Shelly Direct"),
          h(Badge, { variant: "outline", className: "text-xs font-normal" }, "v" + version)
        ),
        h("div", { className: "flex items-center gap-2" },
          h("span", { className: "text-xs text-muted-foreground" },
            store.lastUpdate ? "updated " + timeAgo(store.lastUpdate) : "not updated yet"),
          h(Button, { size: "sm", variant: "outline", onClick: loadDevices, disabled: store.discovering }, "Refresh"),
          h(Button, { size: "sm", onClick: discover, disabled: store.discovering },
            store.discovering ? h("span", { className: "sd-spin mr-1" }) : null,
            store.discovering ? "Discovering…" : "Discover")
        )
      ),
      fatal ? h(Badge, { variant: "destructive", className: "sd-err text-xs" }, "backend: " + fatal) : null,
      !store.loaded && !fatal ? h("div", { className: "text-sm text-muted-foreground" }, "Loading devices…") : null,
      store.loaded && !fatal && devices.length === 0
        ? h(Card, { className: "bg-background/40" },
            h(CardContent, { className: "flex flex-col items-center gap-2 py-12 text-center" },
              h("div", { className: "text-lg font-medium" }, "No Shelly devices yet"),
              h("div", { className: "max-w-md text-sm text-muted-foreground" },
                "Press Discover to scan your LAN for Shelly devices (Gen 1/2/3). Everything is controlled directly on your local network — no Home Assistant, no cloud."),
              h(Button, { size: "sm", className: "mt-2", onClick: discover, disabled: store.discovering },
                store.discovering ? h("span", { className: "sd-spin mr-1" }) : null,
                store.discovering ? "Discovering…" : "Discover")
            ))
        : null,
      devices.length
        ? h("div", { className: "sd-grid" }, devices.map(function (d) {
            return h(DeviceCard, {
              key: d.mac || d.id,
              device: d,
              status: store.statuses[d.mac],
              error: store.errors[d.mac],
              pending: !!pending[d.mac],
              act: function (payload) { act(d.mac, payload); }
            });
          }))
        : null,
      h("div", { className: "flex flex-wrap items-center gap-2 border-t border-border pt-3 text-xs text-muted-foreground" },
        h(Badge, { variant: "outline", className: "text-xs font-normal" },
          "verify writes: " + (settings ? (settings.verify_writes ? "on" : "off") : "…")),
        h(Badge, { variant: "outline", className: "text-xs font-normal" },
          "auth: " + (settings ? (settings.auth_configured ? "configured" : "not set") : "…")),
        h("span", { className: "ml-auto font-mono text-xs" }, onlineCount + "/" + devices.length + " online")
      )
    );
  }

  registry.register("shelly-direct", App);
})();
