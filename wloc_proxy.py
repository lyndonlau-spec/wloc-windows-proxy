import json
import os
import re
import sys
import threading
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional, Union

APP_VERSION = "1.0.0"
APP_HOME = Path(os.environ.get("WLOC_HOME", Path(__file__).resolve().parent))
SETTINGS_PATH = APP_HOME / "settings.json"
SETTINGS_PORT = int(os.environ.get("WLOC_SETTINGS_PORT", "8081"))
DEFAULT_SETTINGS = {
    "enabled": False,
    "longitude": 113.94114,
    "latitude": 22.544577,
    "accuracy": 25,
}
MAC_RE = re.compile(r"^[0-9a-fA-F]{1,2}(?::[0-9a-fA-F]{1,2}){5}$")

INDEX_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>WLOC 定位设置</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" crossorigin="">
  <style>
    *{box-sizing:border-box}body{margin:0;background:#f3f5f8;color:#172033;font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
    main{max-width:1100px;margin:28px auto;padding:0 20px}.card{background:#fff;border:1px solid #dfe4ec;border-radius:14px;box-shadow:0 8px 30px #23304a12;overflow:hidden}
    header{display:flex;justify-content:space-between;align-items:center;padding:18px 22px;border-bottom:1px solid #e8ebf0}h1{font-size:20px;margin:0}.state{font-weight:650}.on{color:#087f5b}.off{color:#c92a2a}
    #map{height:520px;background:#dfe6ed}.controls{display:grid;grid-template-columns:1fr 1fr 140px auto auto;gap:10px;padding:16px}label{display:flex;flex-direction:column;gap:5px;color:#586174;font-size:13px}
    input{height:40px;border:1px solid #ccd3df;border-radius:8px;padding:0 10px;font:inherit;color:#172033}button{align-self:end;height:40px;border:0;border-radius:8px;padding:0 16px;font-weight:650;cursor:pointer}
    .primary{background:#2563eb;color:white}.secondary{background:#e8edf5;color:#263247}.danger{background:#fee2e2;color:#b42318}.message{min-height:24px;padding:0 18px 14px;color:#586174}
    @media(max-width:780px){#map{height:430px}.controls{grid-template-columns:1fr 1fr}.controls label:nth-child(3){grid-column:1/2}.controls button{width:100%}}
  </style>
</head>
<body><main><section class="card">
  <header><h1>Windows WLOC 定位设置</h1><div id="state" class="state off">读取中</div></header>
  <div id="map"></div>
  <div class="controls">
    <label>纬度<input id="lat" type="number" min="-90" max="90" step="0.00000001"></label>
    <label>经度<input id="lon" type="number" min="-180" max="180" step="0.00000001"></label>
    <label>精度（米）<input id="accuracy" type="number" min="1" max="1000" step="1"></label>
    <button id="locate" class="secondary">定位到坐标</button>
    <button id="save" class="primary">保存并启用</button>
    <button id="disable" class="danger">停止模拟</button>
  </div>
  <div id="message" class="message">点击地图选择位置，或直接输入 WGS‑84 坐标。</div>
</section></main>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" crossorigin=""></script>
<script>
const $=id=>document.getElementById(id), message=$('message');
const map=L.map('map',{zoomControl:true}).setView([22.544577,113.94114],13);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© OpenStreetMap'}).addTo(map);
const marker=L.marker([22.544577,113.94114],{draggable:true}).addTo(map);
function setInputs(lat,lon){$('lat').value=Number(lat).toFixed(8);$('lon').value=Number(lon).toFixed(8)}
function move(lat,lon,zoom=true){if(!Number.isFinite(lat)||!Number.isFinite(lon)||lat<-90||lat>90||lon<-180||lon>180)throw Error('经纬度超出范围');marker.setLatLng([lat,lon]);if(zoom)map.setView([lat,lon],Math.max(map.getZoom(),15));setInputs(lat,lon)}
function showState(enabled){const el=$('state');el.textContent=enabled?'模拟已启用':'当前为透传';el.className='state '+(enabled?'on':'off')}
map.on('click',e=>move(e.latlng.lat,e.latlng.lng,false));marker.on('dragend',e=>{const p=e.target.getLatLng();setInputs(p.lat,p.lng)});
$('locate').onclick=()=>{try{move(Number($('lat').value),Number($('lon').value))}catch(e){message.textContent=e.message}};
$('save').onclick=async()=>{try{const body={enabled:true,latitude:Number($('lat').value),longitude:Number($('lon').value),accuracy:Number($('accuracy').value)};const r=await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const out=await r.json();if(!r.ok)throw Error(out.error||'保存失败');showState(true);message.textContent=`已启用：${out.latitude}, ${out.longitude}，精度 ${out.accuracy} 米`}catch(e){message.textContent=e.message}};
$('disable').onclick=async()=>{try{const r=await fetch('/api/disable',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});const out=await r.json();if(!r.ok)throw Error(out.error||'操作失败');showState(false);message.textContent='已停止修改，WLOC 响应将原样放行'}catch(e){message.textContent=e.message}};
(async()=>{try{const r=await fetch('/api/settings');const s=await r.json();move(s.latitude,s.longitude);$('accuracy').value=s.accuracy;showState(s.enabled)}catch(e){message.textContent='读取设置失败：'+e.message}})();
</script></body></html>"""


class SettingsStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        self.data = dict(DEFAULT_SETTINGS)
        self.load()

    def load(self) -> dict[str, Any]:
        with self.lock:
            try:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                self.data = self.validate(saved)
            except FileNotFoundError:
                pass
            except Exception as exc:
                print(f"[settings] ignored invalid settings: {exc}", file=sys.stderr)
            return dict(self.data)

    def get(self) -> dict[str, Any]:
        with self.lock:
            return dict(self.data)

    def update(self, values: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            merged = {**self.data, **values}
            self.data = self.validate(merged)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temp, self.path)
            return dict(self.data)

    @staticmethod
    def validate(values: dict[str, Any]) -> dict[str, Any]:
        enabled = values.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ValueError("enabled 必须是布尔值")
        longitude = float(values.get("longitude", DEFAULT_SETTINGS["longitude"]))
        latitude = float(values.get("latitude", DEFAULT_SETTINGS["latitude"]))
        accuracy = int(values.get("accuracy", DEFAULT_SETTINGS["accuracy"]))
        if not -180 <= longitude <= 180:
            raise ValueError("经度必须在 -180 到 180 之间")
        if not -90 <= latitude <= 90:
            raise ValueError("纬度必须在 -90 到 90 之间")
        if not 1 <= accuracy <= 1000:
            raise ValueError("精度必须在 1 到 1000 米之间")
        return {"enabled": enabled, "longitude": longitude, "latitude": latitude, "accuracy": accuracy}


STORE = SettingsStore(SETTINGS_PATH)


class SettingsHandler(BaseHTTPRequestHandler):
    server_version = "WlocSettings/1.0"

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _json(self, status: int, data: dict[str, Any]) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _local_only(self) -> bool:
        return self.client_address[0] in {"127.0.0.1", "::1"}

    def do_GET(self) -> None:
        if not self._local_only():
            self.send_error(403)
            return
        path = self.path.split("?", 1)[0]
        if path == "/":
            body = INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/settings":
            self._json(200, STORE.get())
        elif path == "/health":
            self._json(200, {"ok": True, "version": APP_VERSION, **STORE.get()})
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        if not self._local_only():
            self.send_error(403)
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            self._json(415, {"error": "Content-Type 必须是 application/json"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 4096:
                raise ValueError("请求体过大")
            values = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(values, dict):
                raise ValueError("请求体必须是 JSON 对象")
            path = self.path.split("?", 1)[0]
            if path == "/api/settings":
                result = STORE.update(values)
            elif path == "/api/disable":
                result = STORE.update({"enabled": False})
            else:
                self.send_error(404)
                return
            self._json(200, result)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})


@dataclass
class PatchStats:
    wifi: int = 0
    cell: int = 0
    locations: int = 0
    skipped: int = 0

    @property
    def changes(self) -> int:
        return self.wifi + self.cell + self.locations


@dataclass(frozen=True)
class ProtoField:
    field_no: int
    wire_type: int
    value: Union[int, bytes]
    raw: bytes


def decode_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    for _ in range(10):
        if offset >= len(data):
            raise ValueError("truncated varint")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7
    raise ValueError("varint too long")


def encode_varint(value: int) -> bytes:
    if value < 0:
        value += 1 << 64
    if not 0 <= value < 1 << 64:
        raise ValueError("varint out of 64-bit range")
    out = bytearray()
    while value >= 0x80:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def parse_fields(data: bytes) -> list[ProtoField]:
    fields: list[ProtoField] = []
    offset = 0
    while offset < len(data):
        start = offset
        tag, offset = decode_varint(data, offset)
        field_no, wire_type = tag >> 3, tag & 7
        if field_no == 0:
            raise ValueError("invalid protobuf field 0")
        if wire_type == 0:
            value, offset = decode_varint(data, offset)
        elif wire_type == 1:
            end = offset + 8
            if end > len(data):
                raise ValueError("truncated fixed64")
            value, offset = data[offset:end], end
        elif wire_type == 2:
            size, offset = decode_varint(data, offset)
            end = offset + size
            if end > len(data):
                raise ValueError("truncated bytes field")
            value, offset = data[offset:end], end
        elif wire_type == 5:
            end = offset + 4
            if end > len(data):
                raise ValueError("truncated fixed32")
            value, offset = data[offset:end], end
        else:
            raise ValueError(f"unsupported protobuf wire type {wire_type}")
        fields.append(ProtoField(field_no, wire_type, value, data[start:offset]))
    return fields


def encode_field(field_no: int, wire_type: int, value: Union[int, bytes]) -> bytes:
    tag = encode_varint(field_no * 8 + wire_type)
    if wire_type == 0 and isinstance(value, int):
        return tag + encode_varint(value)
    if wire_type in {1, 5} and isinstance(value, bytes):
        return tag + value
    if wire_type == 2 and isinstance(value, bytes):
        return tag + encode_varint(len(value)) + value
    raise ValueError("invalid protobuf field value")


def patch_location(data: bytes, settings: dict[str, Any], stats: PatchStats) -> bytes:
    fields = parse_fields(data)
    if not any(f.field_no == 1 and f.wire_type == 0 for f in fields):
        return data
    if not any(f.field_no == 2 and f.wire_type == 0 for f in fields):
        return data
    out = bytearray()
    for field in fields:
        if field.field_no == 1 and field.wire_type == 0:
            out += encode_field(1, 0, round(100_000_000 * settings["latitude"]))
        elif field.field_no == 2 and field.wire_type == 0:
            out += encode_field(2, 0, round(100_000_000 * settings["longitude"]))
        elif field.field_no == 3 and field.wire_type == 0:
            out += encode_field(3, 0, settings["accuracy"])
        else:
            out += field.raw
    stats.locations += 1
    return bytes(out)


def patch_wifi(data: bytes, settings: dict[str, Any], stats: PatchStats) -> bytes:
    fields = parse_fields(data)
    mac_ok = any(
        field.field_no == 1
        and field.wire_type == 2
        and isinstance(field.value, bytes)
        and MAC_RE.fullmatch(field.value.decode("ascii", errors="ignore"))
        for field in fields
    )
    if not mac_ok:
        return data
    changed = False
    out = bytearray()
    for field in fields:
        if field.field_no == 2 and field.wire_type == 2 and isinstance(field.value, bytes):
            try:
                patched = patch_location(field.value, settings, stats)
                changed |= patched != field.value
                out += encode_field(2, 2, patched)
            except ValueError:
                stats.skipped += 1
                out += field.raw
        else:
            out += field.raw
    if changed:
        stats.wifi += 1
    return bytes(out)


def patch_cell(data: bytes, settings: dict[str, Any], stats: PatchStats) -> bytes:
    fields = parse_fields(data)
    changed = False
    out = bytearray()
    for field in fields:
        if field.field_no == 5 and field.wire_type == 2 and isinstance(field.value, bytes):
            try:
                patched = patch_location(field.value, settings, stats)
                changed |= patched != field.value
                out += encode_field(5, 2, patched)
            except ValueError:
                stats.skipped += 1
                out += field.raw
        else:
            out += field.raw
    if changed:
        stats.cell += 1
    return bytes(out)


def patch_payload(data: bytes, settings: dict[str, Any], stats: PatchStats) -> bytes:
    out = bytearray()
    for field in parse_fields(data):
        if field.field_no == 2 and field.wire_type == 2 and isinstance(field.value, bytes):
            out += encode_field(2, 2, patch_wifi(field.value, settings, stats))
        elif field.field_no in {22, 24} and field.wire_type == 2 and isinstance(field.value, bytes):
            out += encode_field(field.field_no, 2, patch_cell(field.value, settings, stats))
        else:
            out += field.raw
    return bytes(out)


def patch_frame(data: bytes, base: int, settings: dict[str, Any]) -> tuple[bytes, PatchStats]:
    if len(data) < base + 10:
        raise ValueError("body too short")
    size = int.from_bytes(data[base + 8 : base + 10], "big")
    if size <= 0 or base + 10 + size > len(data):
        raise ValueError("invalid frame length")
    payload = data[base + 10 : base + 10 + size]
    stats = PatchStats()
    patched = patch_payload(payload, settings, stats)
    if stats.changes <= 0 or patched == payload:
        raise ValueError("frame has no patchable WLOC payload")
    if len(patched) > 65535:
        raise ValueError("patched payload is too large")
    return data[: base + 8] + len(patched).to_bytes(2, "big") + patched + data[base + 10 + size :], stats


def patch_wloc_body(data: bytes, settings: dict[str, Any]) -> tuple[bytes, PatchStats, str]:
    preferred = list(range(0, 18, 2))
    upper = min(96, max(0, len(data) - 10))
    offsets = preferred + [offset for offset in range(upper + 1) if offset not in preferred]
    for offset in offsets:
        try:
            patched, stats = patch_frame(data, offset, settings)
            return patched, stats, f"frame@{offset}"
        except ValueError:
            pass
    for offset in range(min(256, len(data)) + 1):
        stats = PatchStats()
        try:
            suffix = data[offset:]
            patched = patch_payload(suffix, settings, stats)
            if stats.changes > 0 and patched != suffix:
                return data[:offset] + patched, stats, f"raw@{offset}"
        except ValueError:
            pass
    raise ValueError("no patchable WLOC payload found")


class WlocAddon:
    def __init__(self) -> None:
        self.httpd: Optional[ThreadingHTTPServer] = None
        self.thread: Optional[threading.Thread] = None

    def running(self) -> None:
        from mitmproxy import ctx

        self.httpd = ThreadingHTTPServer(("127.0.0.1", SETTINGS_PORT), SettingsHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="wloc-settings", daemon=True)
        self.thread.start()
        ctx.log.info(f"[wloc] settings UI: http://127.0.0.1:{SETTINGS_PORT}")

    def done(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()

    def response(self, flow: Any) -> None:
        from mitmproxy import ctx

        host = flow.request.host.lower()
        if host not in {"gs-loc.apple.com", "gs-loc-cn.apple.com"}:
            return
        if not flow.request.path.startswith("/clls/wloc") or flow.response is None:
            return
        settings = STORE.get()
        if not settings["enabled"]:
            ctx.log.info("[wloc] pass-through: simulation disabled")
            return
        if flow.response.status_code != 200:
            ctx.log.warn(f"[wloc] pass-through: upstream status={flow.response.status_code}")
            return
        try:
            body = flow.response.content
            if not body:
                raise ValueError("empty response body")
            patched, stats, mode = patch_wloc_body(body, settings)
            flow.response.content = patched
            flow.response.headers["X-WLOC-Proxy"] = f"windows-mitmproxy/{APP_VERSION}"
            flow.response.headers["X-WLOC-Patched-Locations"] = str(stats.locations)
            flow.response.headers["X-WLOC-Target"] = f'{settings["latitude"]},{settings["longitude"]}'
            ctx.log.info(
                f"[wloc] patched mode={mode} locations={stats.locations} "
                f"wifi={stats.wifi} cell={stats.cell} skipped={stats.skipped}"
            )
        except Exception as exc:
            flow.response.headers["X-WLOC-Error"] = str(exc)[:160]
            ctx.log.error(f"[wloc] patch failed: {exc}")


def signed64(value: int) -> int:
    return value - (1 << 64) if value >= 1 << 63 else value


def self_test() -> None:
    settings = {"enabled": True, "latitude": 40.7128, "longitude": -74.006, "accuracy": 18}
    location = encode_field(1, 0, round(22.544577 * 100_000_000)) + encode_field(2, 0, round(113.94114 * 100_000_000)) + encode_field(3, 0, 50)
    wifi = encode_field(1, 2, b"aa:bb:cc:dd:ee:ff") + encode_field(2, 2, location)
    cell = encode_field(5, 2, location)
    payload = encode_field(2, 2, wifi) + encode_field(22, 2, cell)
    framed = b"\x00" * 8 + len(payload).to_bytes(2, "big") + payload
    patched, stats, mode = patch_wloc_body(framed, settings)
    size = int.from_bytes(patched[8:10], "big")
    root = parse_fields(patched[10 : 10 + size])
    wifi_out = parse_fields(next(f.value for f in root if f.field_no == 2))
    location_out = parse_fields(next(f.value for f in wifi_out if f.field_no == 2))
    values = {f.field_no: signed64(int(f.value)) for f in location_out if f.wire_type == 0}
    assert values == {1: 4_071_280_000, 2: -7_400_600_000, 3: 18}
    assert asdict(stats) == {"wifi": 1, "cell": 1, "locations": 2, "skipped": 0}
    print(json.dumps({"ok": True, "mode": mode, "stats": asdict(stats), "values": values}, sort_keys=True))


if __name__ == "__main__":
    self_test()
else:
    addons = [WlocAddon()]
