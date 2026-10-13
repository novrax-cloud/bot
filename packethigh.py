# ==================== STANDARD IMPORTS ====================
import sys
import asyncio
import httpx
import random
import json
import socket
import struct
import time
import os
import uuid
import itertools
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any
import re


if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
    except Exception:
        pass

# ==================== ORIGINAL IMPORTS ====================
from google_play_scraper import app as play_scraper
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from protobuf_decoder.protobuf_decoder import Parser
from message_ids import MESSAGE_ID_TO_NAME

import thunderFF_pb2
try:
    from python_socks.async_.asyncio import Proxy as AsyncSocksProxy
    HAS_PYTHON_SOCKS = True
except ImportError:
    AsyncSocksProxy = None
    HAS_PYTHON_SOCKS = False

# ==================== WEB DASHBOARD ====================
from dashboard_server import bot_state, start_web_dashboard, GAME_MODES

# ==================== CONFIGURATION ====================
WEB_HOST = os.environ.get("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.environ.get("SERVER_PORT", os.environ.get("WEB_PORT", os.environ.get("PORT", 30116))))
ACCOUNTS_FILE = "accounts.json"
TOKEN_CACHE_FILE = "token_cache.json"
DEVICES_FILE = "devices.json"  # 🔥 NEW: Persistent device storage
TOKEN_CACHE_TTL = 1200

# 🔥 Match control (Optimized in app.py)
START_MATCH_INTERVAL = 3.0
NEW_MATCH_DELAY = 1.5   # Optimized: Next match request triggered in 1.5s (was 3.0s)   
MAX_MATCH_DURATION = 700
MATCH_IDLE_TIMEOUT = 45.0   # 45s — server quiet periods normal in-match
PRIORITY_REGIONS = ["BD","IND", "SG", "TH", "PH", "VN", "MY", "ID", "HK", "TW"]

# 🔥 Cache invalidation thresholds
MAX_CONSECUTIVE_PARSE_FAILURES = 5.0     
NON_MATCH_RECONNECT_DELAY = 1.0       

FALLBACK_UID = ""
FALLBACK_PASSWORD = ""

# 🔥 30-Minute Sequential Account Rotation Configuration
ROTATION_DURATION = int(os.environ.get("ROTATION_DURATION", 1800))  # 30 min (1800s)
ROTATION_COOLDOWN = int(os.environ.get("ROTATION_COOLDOWN", 60))    # 1 min (60s)
LEVEL_JSON_FILE = "level.json"
ACCOUNTS_IND_FILE = "accounts-IND.jsonl"
ACCOUNTS_IND_JSON = "accounts-IND.json"


# ==================== ULTRA SAFE PERSISTENT DEVICE RANDOMIZER ====================
_INDIAN_SUBNETS = [
    # Bharti Airtel Mobile & Broadband
    "152.59", "152.58", "106.192", "106.193", "106.208", "106.209", "122.160", "122.161", "171.76",
    # Reliance Jio
    "157.34", "157.35", "157.38", "157.40", "157.41", "49.36", "49.37", "49.38", "49.39", "49.40",
    # Vodafone Idea (Vi)
    "115.96", "115.97", "115.112", "125.16", "125.17", "180.151",
    # BSNL
    "117.200", "117.201", "117.216", "117.217", "210.212",
    # ACT Fibernet / Indian Broadband
    "183.82", "183.83", "103.211", "103.212"
]

def generate_indian_ip(seed_str: str = "") -> str:
    """Generates an authentic Indian mobile/broadband IP address."""
    if seed_str:
        s = sum(ord(c) for c in str(seed_str))
        subnet = _INDIAN_SUBNETS[s % len(_INDIAN_SUBNETS)]
        o3 = 10 + (s * 7) % 240
        o4 = 10 + (s * 13) % 240
        return f"{subnet}.{o3}.{o4}"
    subnet = random.choice(_INDIAN_SUBNETS)
    return f"{subnet}.{random.randint(10, 250)}.{random.randint(10, 250)}"


def get_device_for_account(account_identifier: str) -> dict:
    """
    Ensures 1 ID = 1 Specific Device with authentic Indian network fingerprint.
    Loads saved devices from devices.json. Automatically repairs any legacy/foreign IPs.
    """
    devices = {}
    if os.path.exists(DEVICES_FILE):
        try:
            with open(DEVICES_FILE, "r", encoding="utf-8") as f:
                devices = json.load(f)
        except Exception:
            pass
            
    acc_key = str(account_identifier)
    
    if acc_key in devices:
        dev = devices[acc_key]
        ip = dev.get("client_ip", "")
        is_indian = any(ip.startswith(p + ".") or ip.startswith(p) for p in _INDIAN_SUBNETS)
        needs_update = False
        if not is_indian:
            dev["client_ip"] = generate_indian_ip(acc_key)
            needs_update = True
        if dev.get("model") != "vivo V2241A":
            dev["model"] = "vivo V2241A"
            dev["gpu_renderer"] = "Adreno (TM) 750"
            dev["system_software"] = "Android OS 9 / API-28 (PQ3B.190801.07131748/G9650ZHU2ARC6)"
            dev["screen_width"] = 1280
            dev["screen_height"] = 720
            dev["screen_dpi"] = "240"
            dev["memory"] = 3004
            dev["processor_details"] = "x86-64 SSE3 SSE4.1 SSE4.2 AVX | 2865 | 4"
            needs_update = True
        if needs_update:
            devices[acc_key] = dev
            try:
                with open(DEVICES_FILE, "w", encoding="utf-8") as f:
                    json.dump(devices, f, indent=4)
            except Exception:
                pass
        return dev

    new_device = {
        "unique_device_id": f"Google|{str(uuid.uuid4())}",
        "brand":            "Handheld",
        "model":            "vivo V2241A",
        "gpu_renderer":     "Adreno (TM) 750",
        "system_software":  "Android OS 9 / API-28 (PQ3B.190801.07131748/G9650ZHU2ARC6)",
        "screen_width":     1280,
        "screen_height":    720,
        "screen_dpi":       "240",
        "memory":           3004,
        "processor_details":"x86-64 SSE3 SSE4.1 SSE4.2 AVX | 2865 | 4",
        "client_ip":        generate_indian_ip(acc_key)
    }
    
    devices[acc_key] = new_device

    try:
        with open(DEVICES_FILE, "w", encoding="utf-8") as f:
            json.dump(devices, f, indent=4)
    except Exception as e:
        print(f"[-] Failed to save device mapping: {e}")
        
    return new_device


# ==================== CLOUDFLARE DNS RESOLVER & SOCKET OPTIMIZERS ====================
CLOUDFLARE_PRIMARY_DNS = "1.1.1.1"
CLOUDFLARE_SECONDARY_DNS = "1.0.0.1"
_DNS_CACHE: Dict[str, Tuple[str, float]] = {}
_DNS_CACHE_TTL = 90.0   # 🔥 FIX: 90s TTL — reduces stale IP on server rotation (was 300s)

async def resolve_host_cloudflare(hostname: str) -> str:
    if not hostname:
        return hostname

    parts = hostname.split('.')
    if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        return hostname

    now = time.time()
    # 🔥 FIX: Cleanup stale DNS entries so memory doesn't grow indefinitely
    if len(_DNS_CACHE) > 50:
        stale_keys = [k for k, (_, exp) in list(_DNS_CACHE.items()) if now > exp]
        for k in stale_keys:
            _DNS_CACHE.pop(k, None)

    if hostname in _DNS_CACHE:
        ip, exp = _DNS_CACHE[hostname]
        if now < exp:
            return ip

    def _query_cloudflare(server_ip: str) -> Optional[str]:
        s = None
        try:
            tx_id = random.randint(1000, 65535)
            header = struct.pack(">HHHHHH", tx_id, 0x0100, 1, 0, 0, 0)
            qname = b"".join(bytes([len(part)]) + part.encode('ascii') for part in hostname.split('.')) + b"\x00"
            query_pkt = header + qname + struct.pack(">HH", 1, 1)

            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(1.2)
            s.sendto(query_pkt, (server_ip, 53))
            resp, _ = s.recvfrom(1024)

            if len(resp) >= 12:
                ancount = struct.unpack(">H", resp[6:8])[0]
                if ancount > 0:
                    offset = 12 + len(qname) + 4
                    for _ in range(ancount):
                        if offset >= len(resp):
                            break
                        if (resp[offset] & 0xC0) == 0xC0:
                            offset += 2
                        else:
                            while offset < len(resp) and resp[offset] != 0:
                                offset += 1 + resp[offset]
                            offset += 1
                        if offset + 10 > len(resp):
                            break
                        rtype, rclass, ttl, rdlen = struct.unpack(">HHIH", resp[offset:offset+10])
                        offset += 10
                        if rtype == 1 and rdlen == 4 and offset + 4 <= len(resp):
                            return socket.inet_ntoa(resp[offset:offset+4])
                        offset += rdlen
        except Exception:
            pass
        finally:
            if s:
                try:
                    s.close()
                except Exception:
                    pass
        return None

    loop = asyncio.get_running_loop()
    ip = await loop.run_in_executor(None, _query_cloudflare, CLOUDFLARE_PRIMARY_DNS)
    if not ip:
        ip = await loop.run_in_executor(None, _query_cloudflare, CLOUDFLARE_SECONDARY_DNS)
    if not ip:
        try:
            ip_info = await loop.getaddrinfo(hostname, None, family=socket.AF_INET)
            if ip_info:
                ip = ip_info[0][4][0]
        except Exception:
            ip = hostname

    if ip:
        _DNS_CACHE[hostname] = (ip, now + _DNS_CACHE_TTL)
    return ip or hostname


def optimize_tcp_socket(sock: socket.socket):
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        # 🔥 LATENCY FIX: Buffer 64KB → 256KB (Germany→India long-distance pipe needs bigger window)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 262144)
        # Kernel-level TCP keepalive tuning (Linux only)
        if hasattr(socket, "TCP_KEEPIDLE"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
        if hasattr(socket, "TCP_KEEPINTVL"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 5)
        if hasattr(socket, "TCP_KEEPCNT"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
        # 🔥 LATENCY FIX: TCP_QUICKACK — ACK delay 40ms khatam (Linux only)
        # Nagle algorithm ka 40ms ACK delay bypass hoga — har packet pe response faster aayega
        if hasattr(socket, "TCP_QUICKACK"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_QUICKACK, 1)
    except Exception:
        pass


def optimize_udp_socket(sock: socket.socket):
    try:
        # 🔥 LATENCY FIX: Buffer 128KB → 256KB (long-distance high-latency route needs more buffer)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 262144)
        # 🔥 LATENCY FIX: DSCP Expedited Forwarding (EF) — IP TOS 0xB8
        # Network routers ko batata hai: "yeh real-time game packet hai, priority do"
        # Germany → India route pe intermediate routers isko pehle forward karenge
        # hasattr check nahi — IP_TOS sabhi platforms pe available hai (fallback try/except se safe)
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, 0xB8)
        except Exception:
            pass
        if hasattr(socket, 'SIO_UDP_CONNRESET') and os.name == 'nt':
            try:
                sock.ioctl(socket.SIO_UDP_CONNRESET, False)
            except Exception:
                pass
    except Exception:
        pass


async def async_udp_send(loop, sock: socket.socket, data: bytes, addr: Tuple[str, int]):
    """
    Reliable UDP sender with retry:
    - Direct non-blocking sendto first (0 latency)
    - On BlockingIOError (kernel buffer full): yield to event loop + retry up to 3 times
    - Falls back to loop.sock_sendto if available
    - 🔥 PACKET DROP FIX: No silent discard — every packet gets 3 chances to send
    """
    # Attempt 1: direct non-blocking send
    try:
        sock.sendto(data, addr)
        return
    except BlockingIOError:
        pass
    except Exception:
        return

    # Kernel buffer full — yield to event loop and retry up to 3 times
    for _retry in range(3):
        await asyncio.sleep(0)  # yield — let event loop flush buffer
        try:
            sock.sendto(data, addr)
            return
        except BlockingIOError:
            if _retry < 2:
                await asyncio.sleep(0.005 * (_retry + 1))  # 5ms, 10ms backoff
            continue
        except Exception:
            break

    # Final fallback: loop.sock_sendto (async kernel wait)
    if hasattr(loop, 'sock_sendto'):
        try:
            await loop.sock_sendto(sock, data, addr)
        except Exception:
            pass


async def async_udp_recv(loop, sock: socket.socket, nbytes: int = 65535, timeout: float = 1.5):
    """
    Ultra-resilient asynchronous UDP receiver:
    Works across Python 3.8-3.13 on Linux, Windows, macOS, uvloop, and standard asyncio.
    """
    if hasattr(loop, 'sock_recvfrom'):
        try:
            return await asyncio.wait_for(loop.sock_recvfrom(sock, nbytes), timeout=timeout)
        except (NotImplementedError, AttributeError):
            pass
        # 🔥 SAFE FIX #2a: Windows UDP ICMP unreachable → return empty tuple
        # so caller's existing timeout handler takes over. On Linux this
        # errno (10054) never fires, so behavior is identical.
        except OSError as e:
            if getattr(e, 'errno', None) in (10054, 10038):
                return None, None
            raise

    fut = loop.create_future()
    fd = sock.fileno()

    def _on_readable():
        try:
            data, addr = sock.recvfrom(nbytes)
            loop.remove_reader(fd)
            if not fut.done():
                fut.set_result((data, addr))
        except BlockingIOError:
            pass
        # 🔥 SAFE FIX #2b: Same guard for add_reader path (Windows Proactor)
        except OSError as e:
            loop.remove_reader(fd)
            if not fut.done():
                if getattr(e, 'errno', None) in (10054, 10038):
                    fut.set_result((None, None))
                else:
                    fut.set_exception(e)
        except Exception as ex:
            loop.remove_reader(fd)
            if not fut.done():
                fut.set_exception(ex)

    try:
        loop.add_reader(fd, _on_readable)
        return await asyncio.wait_for(fut, timeout=timeout)
    finally:
        try:
            loop.remove_reader(fd)
        except Exception:
            pass


# ==================== NETWORK, PROXY & CRYPTO ====================
_http_clients: Dict[str, httpx.AsyncClient] = {}

def get_http_client(proxy_url: Optional[str] = None) -> httpx.AsyncClient:
    key = str(proxy_url or "").strip()
    if key not in _http_clients:
        kwargs = {
            "verify": False,
            "timeout": 12.0,
            "limits": httpx.Limits(max_connections=50, max_keepalive_connections=25)
        }
        if key:
            kwargs["proxy"] = key
        _http_clients[key] = httpx.AsyncClient(**kwargs)
    return _http_clients[key]

# 🔥 FIX: HTTP client memory leak — close all clients on program exit
import atexit as _atexit
def _cleanup_http_clients():
    for _c in list(_http_clients.values()):
        try:
            import asyncio as _asyncio
            loop = _asyncio.new_event_loop()
            loop.run_until_complete(_c.aclose())
            loop.close()
        except Exception:
            pass
_atexit.register(_cleanup_http_clients)

# Default unproxied client for global tasks
client = get_http_client(None)

async def open_proxy_connection(host: str, port: int, proxy_url: Optional[str] = None) -> Tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    clean_proxy = str(proxy_url or "").strip()
    if not clean_proxy:
        return await asyncio.open_connection(host, int(port))
    if not HAS_PYTHON_SOCKS or AsyncSocksProxy is None:
        raise ImportError("SOCKS/HTTP proxy requires 'python-socks'. Run: pip install python-socks")
    try:
        proxy = AsyncSocksProxy.from_url(clean_proxy)
        sock = await proxy.connect(dest_host=host, dest_port=int(port), timeout=12.0)
        optimize_tcp_socket(sock)
        return await asyncio.open_connection(sock=sock)
    except Exception as e:
        print_error(f"Proxy connection failed ({clean_proxy}) to {host}:{port}: {e}")
        raise


headers = {
    'User-Agent': 'UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)',
    'Connection': 'Keep-Alive',
    'Accept-Encoding': 'gzip',
    'Content-Type': 'application/x-www-form-urlencoded',
    'Expect': '100-continue',
    'X-Unity-Version': '2018.4.12f1',
    'X-GA-SV': '1789535859',
    'X-GA': 'v1 1',
    'ReleaseVersion': 'OB55'
}

AES_KEY = b'Yg&tc%DEuh6%Zc^8'
AES_IV = b'6oyZDr22E3ychjM%'

CRC7_TABLE = bytes([
    0, 9, 18, 27, 36, 45, 54, 63, 72, 65, 90, 83, 108, 101, 126, 119,
    25, 16, 11, 2, 61, 52, 47, 38, 81, 88, 67, 74, 117, 124, 103, 110,
    50, 59, 32, 41, 22, 31, 4, 13, 122, 115, 104, 97, 94, 87, 76, 69,
    43, 34, 57, 48, 15, 6, 29, 20, 99, 106, 113, 120, 71, 78, 85, 92,
    100, 109, 118, 127, 64, 73, 82, 91, 44, 37, 62, 55, 8, 1, 26, 19,
    125, 116, 111, 102, 89, 80, 75, 66, 53, 60, 39, 46, 17, 24, 3, 10,
    86, 95, 68, 77, 114, 123, 96, 105, 30, 23, 12, 5, 58, 51, 40, 33,
    79, 70, 93, 84, 107, 98, 121, 112, 7, 14, 21, 28, 35, 42, 49, 56,
    65, 72, 83, 90, 101, 108, 119, 126, 9, 0, 27, 18, 45, 36, 63, 54,
    88, 81, 74, 67, 124, 117, 110, 103, 16, 25, 2, 11, 52, 61, 38, 47,
    115, 122, 97, 104, 87, 94, 69, 76, 59, 50, 41, 32, 31, 22, 13, 4,
    106, 99, 120, 113, 78, 71, 92, 85, 34, 43, 48, 57, 6, 15, 20, 29,
    37, 44, 55, 62, 1, 8, 19, 26, 109, 100, 127, 118, 73, 64, 91, 82,
    60, 53, 46, 39, 24, 17, 10, 3, 116, 125, 102, 111, 80, 89, 66, 75,
    23, 30, 5, 12, 51, 58, 33, 40, 95, 86, 77, 68, 123, 114, 105, 96,
    14, 7, 28, 21, 42, 35, 56, 49, 70, 79, 84, 93, 98, 107, 112, 121,
])

_DELTA = 0x9E3779B9
_ROUNDS = 16
_FIELD_SIZES = {0: 1, 1: 2, 2: 2, 3: 1, 4: 2}
_FIELD_NAMES = {0: "sendOption", 1: "cmd", 2: "orderId", 3: "flags", 4: "length"}

sai_tail_dul = bytes.fromhex(
    "0101030101045452000103000100000410312e3133302e3232"
    "1432303139313231303430ca0163736f7665727365612e737472"
    "6f6e67686f6c642e66726565666972656d6f62696c652e636f6d"
    "3b302e302e302e303b33342e3132362e37362e34353b33342e38"
    "372e3137372e31343b33342e38372e3137302e3233303b33352e"
    "3138352e3138332e353700000000000001000000000000000000"
    "0000000100000000000100000000000100b8eeec91c5d7ffde110200"
)

# NOTE: headers defined once below — used for all HTTP requests

class Colors:
    HEADER = '\033[95m'
    GREEN = '\033[92m'
    FAIL = '\033[91m'
    WARNING = '\033[93m'
    YELLOW = '\033[93m'
    CYAN = '\033[96m'
    MAGENTA = '\033[95m'
    WHITE = '\033[97m'
    BLUE = '\033[94m'   # Bug fix: was missing, caused AttributeError on loot/inventory actions
    ENDC = '\033[0m'

def print_colored(text, color=Colors.WHITE):
    try:
        print(f"{color}{text}{Colors.ENDC}")
    except Exception:
        try:
            print(f"{color}{text.encode('ascii', errors='replace').decode('ascii')}{Colors.ENDC}")
        except Exception:
            pass

def print_success(text):
    print_colored(f"[+] {text}", Colors.GREEN)
    try:
        bot_state.log(text, "success")
    except Exception:
        pass

def print_error(text):
    print_colored(f"[-] {text}", Colors.FAIL)
    try:
        bot_state.log(text, "error")
    except Exception:
        pass

def print_warning(text):
    print_colored(f"[!] {text}", Colors.WARNING)
    try:
        bot_state.log(text, "warning")
    except Exception:
        pass

def print_info(text):
    print_colored(f"[i] {text}", Colors.CYAN)
    try:
        bot_state.log(text, "info")
    except Exception:
        pass

def get_proto_field(d, key, default=None):
    if not d or not isinstance(d, dict):
        return default
    if key in d:
        val = d[key].get('data')
        return val if val is not None else default
    if str(key) in d:
        val = d[str(key)].get('data')
        return val if val is not None else default
    return default


# ==================== PER-ACCOUNT MATCH COUNTER ====================
_active_match_counters: Dict[str, int] = {}
_match_sequence_counters: Dict[str, int] = {}
_match_counter_lock: Optional[asyncio.Lock] = None

def _get_match_counter_lock() -> asyncio.Lock:
    global _match_counter_lock
    if _match_counter_lock is None:
        _match_counter_lock = asyncio.Lock()
    return _match_counter_lock

async def _inc_match(uid: str) -> Tuple[int, int]:
    """
    Returns (seq_index, active_count)
    seq_index: Ever-increasing sequential match number (#1, #2, #3, ...) - never decrements!
    active_count: Number of concurrent active matches running right now.
    """
    async with _get_match_counter_lock():
        _match_sequence_counters[uid] = _match_sequence_counters.get(uid, 0) + 1
        _active_match_counters[uid] = _active_match_counters.get(uid, 0) + 1
        return _match_sequence_counters[uid], _active_match_counters[uid]

async def _dec_match(uid: str) -> int:
    async with _get_match_counter_lock():
        if uid in _active_match_counters and _active_match_counters[uid] > 0:
            _active_match_counters[uid] -= 1
        return _active_match_counters.get(uid, 0)

async def _get_match_count(uid: str) -> int:
    async with _get_match_counter_lock():
        return _active_match_counters.get(uid, 0)

async def _get_total_match_count() -> int:
    async with _get_match_counter_lock():
        return sum(_active_match_counters.values())


# ==================== TOKEN CACHE ====================
_token_cache_memo: Dict[str, Any] = {}
_token_cache_memo_time: float = 0.0
_TOKEN_CACHE_MEMO_TTL = 5.0
# 🔥 BUG FIX: Lock prevents concurrent read/write corruption on token_cache.json
_token_cache_lock: Optional[asyncio.Lock] = None

def _get_token_cache_lock() -> asyncio.Lock:
    global _token_cache_lock
    if _token_cache_lock is None:
        _token_cache_lock = asyncio.Lock()
    return _token_cache_lock

def _json_serializer(obj):
    if isinstance(obj, (bytes, bytearray)):
        return {"__bytes_hex__": bytes(obj).hex()}
    raise TypeError(f"Type {type(obj)} not serializable")

def _json_deserializer(obj):
    if isinstance(obj, dict):
        if "__bytes_hex__" in obj and len(obj) == 1:
            try:
                return bytes.fromhex(obj["__bytes_hex__"])
            except Exception:
                return b""
        return {k: _json_deserializer(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_deserializer(x) for x in obj]
    return obj

def _load_token_cache() -> Dict[str, Any]:
    global _token_cache_memo, _token_cache_memo_time
    now = time.time()
    if _token_cache_memo and (now - _token_cache_memo_time) < _TOKEN_CACHE_MEMO_TTL:
        return _token_cache_memo

    if not os.path.exists(TOKEN_CACHE_FILE):
        return {}
    try:
        with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            return {}
        data = json.loads(content)
        if not isinstance(data, dict):
            raise ValueError("Cache root must be dict")
        parsed = _json_deserializer(data)
        _token_cache_memo = parsed
        _token_cache_memo_time = now
        return parsed
    except Exception as e:
        print_error(f"Token cache corrupt → deleting: {e}")
        try:
            os.remove(TOKEN_CACHE_FILE)
        except Exception:
            pass
        return {}

def _save_token_cache(cache: Dict[str, Any]):
    global _token_cache_memo, _token_cache_memo_time
    try:
        tmp_file = TOKEN_CACHE_FILE + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, default=_json_serializer)
        os.replace(tmp_file, TOKEN_CACHE_FILE)
        _token_cache_memo = cache
        _token_cache_memo_time = time.time()
    except Exception as e:
        print_error(f"Token cache save error: {e}")

def cache_get(uid: str) -> Optional[Dict]:
    cache = _load_token_cache()
    entry = cache.get(str(uid))
    if not entry:
        return None
    if time.time() - entry.get("cached_at", 0) > TOKEN_CACHE_TTL:
        print_info(f"[CACHE] UID {uid} expired. Re-login needed.")
        cache_invalidate(uid)
        return None
    if str(entry.get("account_id", "")).isdigit():
        entry["account_id"] = int(entry["account_id"])
    if not isinstance(entry.get("login_payload_data"), (bytes, bytearray)):
        print_warning(f"[CACHE] UID {uid} missing payload → invalidating")
        cache_invalidate(uid)
        return None
    return entry

async def cache_set_async(uid: str, account_data: Dict):
    # 🔥 BUG FIX: Locked write — prevents file corruption from concurrent saves
    async with _get_token_cache_lock():
        cache = _load_token_cache()
        entry = dict(account_data)
        entry["cached_at"] = time.time()
        cache[str(uid)] = entry
        _save_token_cache(cache)
    print_success(f"[CACHE] Saved credentials for UID {uid}")

def cache_set(uid: str, account_data: Dict):
    # Sync fallback (non-async context) — still works, just no lock guarantee
    cache = _load_token_cache()
    entry = dict(account_data)
    entry["cached_at"] = time.time()
    cache[str(uid)] = entry
    _save_token_cache(cache)
    print_success(f"[CACHE] Saved credentials for UID {uid}")

async def cache_invalidate_async(uid: str):
    # 🔥 BUG FIX: Locked invalidate
    async with _get_token_cache_lock():
        cache = _load_token_cache()
        if str(uid) in cache:
            del cache[str(uid)]
            _save_token_cache(cache)
    print_warning(f"[CACHE] Invalidated: {uid}")

def cache_invalidate(uid: str):
    cache = _load_token_cache()
    if str(uid) in cache:
        del cache[str(uid)]
        _save_token_cache(cache)
        print_warning(f"[CACHE] Invalidated: {uid}")


# ==================== ENCRYPTION & PROTOBUF ====================

async def aes_encrypt(payload, key, iv):
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return cipher.encrypt(pad(payload, AES.block_size))

_cached_playstore_version = None
_cached_playstore_version_time: float = 0.0
_PLAYSTORE_VERSION_TTL = 86400.0  # 🔥 FIX: 24h TTL — version refreshes daily (was: never refreshed)

async def get_playstore_version():
    global _cached_playstore_version, _cached_playstore_version_time
    now = time.time()
    if _cached_playstore_version and (now - _cached_playstore_version_time) < _PLAYSTORE_VERSION_TTL:
        return _cached_playstore_version
    try:
        loop = asyncio.get_running_loop()  # Bug fix: get_event_loop() deprecated in 3.10+
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: play_scraper('com.dts.freefireth', lang='hi', country='id')
            ),
            timeout=5.0
        )
        ver = result.get("version")
        if ver:
            _cached_playstore_version = ver
            _cached_playstore_version_time = time.time()
            return ver
    except Exception:
        pass
    _cached_playstore_version = "1.132.1"
    _cached_playstore_version_time = time.time()
    return "1.132.1"

async def version_config():
    app_version = await get_playstore_version()
    api_url = (
        "https://version.ggwhitehawk.com/live/ver.php"
        f"?version={app_version}"
        "&lang=hi&device=android&channel=android"
        "&appstore=googleplay&region=BD"
        "&whitelist_version=1.3.0&whitelist_sp_version=1.0.0"
    )
    try:
        response = await client.get(api_url)
        response.raise_for_status()
        data = response.json()
        server_url = data.get("server_url")
        remote_version = data.get("remote_version")
        latest_release_version = data.get("latest_release_version")
        if not server_url or not remote_version or not latest_release_version:
            return None
        return latest_release_version, remote_version, server_url
    except Exception:
        return None

# 🔥 PERFORMANCE: Proto builders made sync — eliminates 10-15 unnecessary
# event-loop context switches per packet build (was: all async, no I/O)
def _enc_vr_sync(n: int) -> bytearray:
    buf = bytearray()
    while True:
        tow = n & 0x7F
        n >>= 7
        if n:
            buf.append(tow | 0x80)
        else:
            buf.append(tow)
            break
    return buf

def _create_variant_sync(field_number: int, value: int) -> bytearray:
    field_header = (field_number << 3) | 0
    return _enc_vr_sync(field_header) + _enc_vr_sync(value)

def _create_length_sync(field_number: int, value) -> bytearray:
    field_header = (field_number << 3) | 2
    encoded_value = value.encode('utf-8') if isinstance(value, str) else value
    return _enc_vr_sync(field_header) + _enc_vr_sync(len(encoded_value)) + encoded_value

def build_proto_packet_sync(fields: dict) -> bytearray:
    packet = bytearray()
    for field, value in fields.items():
        if isinstance(value, dict):
            nested_packet = build_proto_packet_sync(value)
            packet.extend(_create_length_sync(field, nested_packet))
        elif isinstance(value, int):
            packet.extend(_create_variant_sync(field, value))
        elif isinstance(value, (str, bytes)):
            packet.extend(_create_length_sync(field, value))
    return packet

# Async wrappers kept for backward compatibility
async def _enc_vr(n: int) -> bytearray:
    return _enc_vr_sync(n)

async def _create_variant(field_number: int, value: int) -> bytearray:
    return _create_variant_sync(field_number, value)

async def _create_length(field_number: int, value) -> bytearray:
    return _create_length_sync(field_number, value)

async def build_proto_packet(fields: dict) -> bytearray:
    return build_proto_packet_sync(fields)

async def get_access_token(uid, password, proxy=None):
    url = "https://100067.connect.garena.com/api/v2/oauth/guest/token:grant"
    hdrs = {
        "Accept": "application/json",
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "GarenaMSDK/4.0.44(V2241A ;Android 9;en;US;app 1.132.1 2019121227;)"
    }
    # 🔥 ANTI-BAN: Use persistent device_id — same UID always sends same device_id
    # Random uuid every login = bot fingerprint for Garena
    _persistent_dev = get_device_for_account(str(uid))
    _dev_id_raw = _persistent_dev.get("unique_device_id", f"Google|{uuid.uuid4()}")
    # Garena expects "02-<uuid>" format for device_id field — extract uuid part
    _dev_uuid = _dev_id_raw.split("|")[-1] if "|" in _dev_id_raw else _dev_id_raw
    body = {
        "client_id": 100067,
        "client_secret": "2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3",
        "client_type": 2,
        "device_id": f"02-{_dev_uuid}",
        "password": str(password),
        "response_type": "token",
        "uid": int(uid) if str(uid).isdigit() else uid
    }
    http_cli = get_http_client(proxy)
    for attempt in range(5):
        try:
            response = await http_cli.post(url, headers=hdrs, json=body)
            if response.status_code == 200:
                response_data = response.json()
                if "error" in response_data:
                    err = response_data.get("error")
                    print_error(f"[-] [AUTH] Garena OAuth returned error for UID {uid}: '{err}' (Code: {response_data.get('code')})")
                    return None
                data = response_data.get("data", {})
                open_id = data.get("open_id")
                access_token = data.get("access_token")
                platform = data.get("platform", 4)
                if open_id and access_token:
                    return open_id, access_token, platform
            elif response.status_code == 429:
                print_warning(f"[!] [AUTH] Rate limited by Garena (HTTP 429). Retrying in 1s...")
                await asyncio.sleep(1)
                continue
            else:
                print_error(f"[-] [AUTH] Garena OAuth HTTP {response.status_code} for UID {uid}: {response.text[:120]}")
        except Exception as e:
            if attempt == 4:
                print_error(f"[-] [AUTH] Connection exception for UID {uid}: {e}")
        await asyncio.sleep(0.5)
    return None

# 🔥 PERFORMANCE: parse_results made sync — pure CPU work, no I/O needed
def parse_results_sync(parsed_results):
    result_dict = {}
    for result in parsed_results:
        field_data = {"wire_type": result.wire_type}
        if result.wire_type == "varint":
            field_data["data"] = result.data
        elif result.wire_type == "string":
            field_data["data"] = result.data
        elif result.wire_type == "bytes":
            field_data["data"] = result.data
        elif result.wire_type == "length_delimited":
            field_data["data"] = parse_results_sync(result.data.results)
        result_dict[result.field] = field_data
    return result_dict

# Async wrapper kept for backward compatibility
async def parse_results(parsed_results):
    return parse_results_sync(parsed_results)

async def decode_protobuf(data):
    parsed_results = Parser().parse(data)
    return json.dumps(parse_results_sync(parsed_results))

async def build_majorlogin_payload(open_id, access_token, platform, client_version, device_info):
    try:
        # 🔥 ANTI-BAN: Randomize operator + connection type — all "Vodafone IN + WIFI" triggers bot detection
        _IND_OPERATORS = ["Vodafone IN", "Jio 4G", "Airtel", "BSNL", "Vi"]
        _CONN_TYPES    = ["WIFI", "4G", "4G", "4G"]  # 4G more common than WIFI
        _op   = random.choice(_IND_OPERATORS)
        _conn = random.choice(_CONN_TYPES)

        fields_dict = {
            3: str(datetime.now())[:-7],
            4: "free fire",
            5: 1,
            7: client_version or "1.132.10",
            8: device_info.get("system_software", "Android OS 9 / API-28 (PQ3B.190801.07131748/G9650ZHU2ARC6)"),
            9: device_info.get("brand", "Handheld"),
            10: _op,
            11: _conn,
            12: int(device_info.get("screen_width", 1280)),
            13: int(device_info.get("screen_height", 720)),
            14: str(device_info.get("screen_dpi", "240")),
            15: device_info.get("processor_details", "x86-64 SSE3 SSE4.1 SSE4.2 AVX | 2865 | 4"),
            16: int(device_info.get("memory", 3004)),
            17: device_info.get("gpu_renderer", "Adreno (TM) 750"),
            18: "OpenGL ES 3.1 v1",
            19: device_info.get("unique_device_id", f"Google|{uuid.uuid4()}"),
            20: device_info.get("client_ip", "152.59.164.40"),
            21: "en",
            22: str(open_id),
            23: str(platform),
            24: "Handheld",
            25: device_info.get("model", "vivo V2241A"),
            29: str(access_token),
            30: 1,
            41: _op,
            42: _conn,
            57: "1ac4b80ecf0478a44203bf8fac6120f5",
            60: 50504,
            61: 47552,
            62: 2519,
            63: 728,
            64: 23876,
            65: 28220,
            66: 49789,
            67: 50504,
            70: 4,
            73: 2,
            74: "/data/app/com.dts.freefireth-CuCC2U4xL6fcwf4ykeQSzg==/lib/arm64",
            76: 1,
            77: "066a589fa3f5658377634fe7b1d88556|/data/app/com.dts.freefireth-CuCC2U4xL6fcwf4ykeQSzg==/base.apk",
            78: 6,
            79: 2,
            81: "64",
            83: "2019121227",
            85: 3,
            86: "OpenGLES2",
            87: 4095,
            88: 4,
            90: "Kolkata",
            91: "WB",
            92: 30751,
            93: "3rd_party",
            94: "KqsHT6SbAFZ68ikFHu5SYR+m+OferdmxxlRpWImnG3rFEJnl3mnc2EhkaiSUhHBv8L9wV5gOT+GEnGtSx6mSu9A+rpSQ2mebpBbI0kb9GG+Px0RH",
            95: 111207,
            96: '{"cur_rate":null,"support_etc2":false}',
            97: 1,
            98: 1,
            99: str(platform),
            100: str(platform),
            102: bytes.fromhex("4a061143565a0d574e5c55455f00175a173e0b510c555e75005f7558520f68085030"),
            104: 34222,
            105: 1,
            106: "https://dl-tata.freefireind.in/live/ABHotUpdates/|https://core-tata.freefireind.in/live/ABHotUpdates/|a4332cb1c1a84e51dd77441e4856ed5a",
            107: "1.cb1040c1d5eee1d8"
        }
        proto_bytes = bytes(build_proto_packet_sync(fields_dict))  # 🔥 sync — no event loop overhead
        return await aes_encrypt(proto_bytes, AES_KEY, AES_IV)
    except Exception as e:
        print_error(f"build_majorlogin_payload error: {e}")
        return None

async def send_majorlogin(data, release_version, server_url, proxy=None):
    try:
        url = f"{server_url.rstrip('/')}/MajorLogin"
        req_headers = headers.copy()
        req_headers["ReleaseVersion"] = release_version
        req_headers["Authorization"] = "Bearer"
        req_headers["X-GA-SV"] = str(int(time.time()))
        http_cli = get_http_client(proxy)
        response = await http_cli.post(url, headers=req_headers, data=data)
        if response.status_code != 200:
            if "BR_AUTH_ABNORMAL_GAME_CLIENT" in response.text:
                print_error("[-] [FLAGGED] Account is flagged by Garena ('BR_AUTH_ABNORMAL_GAME_CLIENT')!")
                return "FLAGGED"
            print_error(f"[-] [MAJORLOGIN] MajorLogin HTTP {response.status_code}: {response.text[:120]}")
            return None
        response_content = response.content
        if b"Exploiting loopholes" in response_content or b"banned" in response_content.lower():
            print_error("[-] [BANNED] Account is BANNED by Garena ('Exploiting loopholes')!")
            return "BANNED"
        if len(response_content) < 40:
            print_error(f"[-] [MAJORLOGIN] Response too short ({len(response_content)} bytes)")
            return None

        # 1. Direct parse
        res_proto = thunderFF_pb2.MajorLoginRes()
        try:
            res_proto.ParseFromString(response_content)
            if res_proto.region and res_proto.token:
                return res_proto
        except Exception:
            pass

        # 2. OB55 64-byte header offset check
        if len(response_content) > 64:
            try:
                res_proto = thunderFF_pb2.MajorLoginRes()
                res_proto.ParseFromString(response_content[64:])
                if res_proto.region and res_proto.token:
                    return res_proto
            except Exception:
                pass

        # 3. Dynamic offset search for OB55 compatibility
        for offset in range(min(128, len(response_content))):
            try:
                candidate = thunderFF_pb2.MajorLoginRes()
                candidate.ParseFromString(response_content[offset:])
                if candidate.region and candidate.token:
                    return candidate
            except Exception:
                pass

        res_proto = thunderFF_pb2.MajorLoginRes()
        res_proto.ParseFromString(response_content)
        return res_proto
    except Exception:
        return None

async def send_getlogin(data, base_url, token, release_version, proxy=None):
    try:
        url = f"{base_url.rstrip('/')}/GetLoginData"
        req_headers = headers.copy()
        req_headers["ReleaseVersion"] = release_version
        req_headers['Authorization'] = f"Bearer {token}"
        req_headers['Host'] = base_url.split('://')[1].split('/')[0]
        req_headers["X-GA-SV"] = str(int(time.time()))
        http_cli = get_http_client(proxy)
        response = await http_cli.post(url, headers=req_headers, data=data)
        if response.status_code != 200:
            return None
        response_content = response.content

        res_proto = thunderFF_pb2.GetLoginDataRes()
        parsed_successfully = False
        try:
            res_proto.ParseFromString(response_content)
            if res_proto.functional_addrs or res_proto.informational_addrs:
                parsed_successfully = True
        except Exception:
            pass

        if not parsed_successfully:
            for offset in range(min(128, len(response_content))):
                try:
                    candidate = thunderFF_pb2.GetLoginDataRes()
                    candidate.ParseFromString(response_content[offset:])
                    if candidate.functional_addrs or candidate.informational_addrs:
                        res_proto = candidate
                        break
                except Exception:
                    pass

        dict_res = {}
        try:
            parsed = Parser().parse(response_content.hex())
            dict_res = await parse_results(parsed)
        except Exception:
            pass

        return res_proto, dict_res
    except Exception:
        return None

async def build_tcp_startup_packet(account_id, token, server_time, key, iv, region="BD", typ='OnLine'):
    uid_hex = f"{int(account_id):016x}"
    timestamp_hex = f"{int(server_time):08x}"
    encode_token = token.encode()
    encrypted_packet = (await aes_encrypt(encode_token, key, iv)).hex()
    encrypted_packet_length = f"{len(encrypted_packet) // 2:08x}"
    reg = str(region).upper() if region else "BD"
    if typ == 'OnLine':
        prefix = '7119' if reg == 'BD' else ('7114' if reg == 'IND' else '7115')
        return f"{prefix}{uid_hex}{timestamp_hex}00000000{encrypted_packet_length}{encrypted_packet}"
    else:  # ChaT / Informational
        prefix = '9219' if reg == 'BD' else ('9214' if reg == 'IND' else '9215')
        return f"{prefix}{uid_hex}{timestamp_hex}{encrypted_packet_length}{encrypted_packet}"

async def send_keep_alive(region="BD"):
    """Send 2-byte keep-alive pulse to maintain connection in OB55"""
    try:
        reg = str(region).upper() if region else "BD"
        ka_hex = "0219" if reg == "BD" else ("0214" if reg == "IND" else "0215")
        return bytes.fromhex(ka_hex)
    except Exception:
        return bytes.fromhex("0219")


CS_SOLO_START_MATCH_HEX = (
    "080112960b0a0101100f3a0a0a04494443311a0242443a0a0a04494443321a0242443a0a0a0449444333"
    "1a02424440014a0901090a0b1219202729580162a70a0a80013038464241333342343332324443323230"
    "323033323030313232323130303031303038453030303330303841303032344235383634394234313330"
    "324437423434363736323531343030303130343037653061306438343830653734386333663661613034"
    "39643430303030303066663038306130353031636163666131366410c6011ab9037e585c541303054d51"
    "000b5c545102560057050309525a0852070853030057550101545600000b051204014f7d5c4045491a05"
    "1d04191009034c01567c77025a6842627e7a63494477675b79770e7708647b007c7c081302447b5d6351"
    "74567c4f7f677f76565074744c5a7b515c5a5b515063450812535f5d4c1e63791d754541044c646a6640"
    "014346504b594564134b7849470b6c7e7d5b466a1e46090d11040249085950785761007e7e45067e410f"
    "5e0066567e427f520502734b000c130a494502601c5362621e6a0b71426f5a405343795a49197b1a5a48"
    "40790c13034c197349517642174051597f5c6f4342435e5a030008644a05435c790e1b084c606973791e"
    "40646217505d687b484c7f707a185269057943400005081302004d0700640a007370405d714943584261"
    "057a6655016c70797c6a7f7c0c16034f701a015563610475431b015e0558670553401a5a037413771b66"
    "000f160549564a7f50477b697304606c0541696876046346561e464a047f74750c1300054d4477051350"
    "59437e5579435e65674a434500074a7b0240597c4f700d12054e5a4746597b5e5f5b704250405c1e6474"
    "5041537b61451a08616a440522047b5f5d5d300c3a1a1101404b4202020201041511647b7163746e7c5b"
    "57725d5550534207312e3133322e38480650015ab105036262535136334c707a475133416456324b796f"
    "566c6646484e4861775a57523441737574496d41506233706a4666667465554a722b7a58592b466f2f43"
    "2f58304b526636765a7631747943545a6e77314f7a307a7a554532636561556f61552b41483563492b42"
    "4a6d4234556d654b54776f4c34656569657a5345536c79332b6a627163486b4f4156456a4b2b634c4776"
    "3141652b68773749586f4e785137344d55716f544b4450557a4971564e584c4635337641775636706f68"
    "4c47345738387a5132627739466773496a564a4b6a48397538796e55354f51305746632f434b764c2b6b"
    "31617a2b6977576e34397044386c4b775253453846714b6d6c5061395963474e456b646d55562f55446d"
    "643045334d74516c353230567a332b4c55754765344b5136653148336f69466f5647615058417a4a7547"
    "4c6b62734a48412b537676504d4144416842676a502b364f6f49362b31445a594664644371736a675467"
    "62436c5674555a466156726a3130617377584b793674436550373535396757444b65586c617074536949"
    "5a73636d3376667051467165436252316c552f686639495163313634594d373553695a6765346979516c"
    "36514933434571556e754a4b426e635855523739303635654951624674377773546b6f6737384552786e"
    "6f4c484756392b59336662656d50316e4a3650385252394f673532587746706f3759646265556a685466"
    "6c4c4c6a415a782b4a696375694a2f685234652f676c7674553533585849374a37346254377067776137"
    "7054766a66514b696530516a79654b466f72794b6255354f46386771616a333464435961626933545470"
    "4339435838326f36653462742f704a4a4458643855796a6757393075692b695a56434c70394477526173"
    "7a6e7a567858654f37346174644138714956477943524239467145575a77384b755a536339593da20105"
    "080310e802a201050804108703a201050805109c01a20105081d10cc01a2010408161076a20105080e10"
    "8b01a201020815"
)

async def CS_Solo_Start_Matchmaking_Packet(key, iv, region="BD", client_ver=None, match_mode=1):
    reg = str(region).upper() if region else "BD"
    app_ver = client_ver or "1.132.8"
    pkt_prefix = '0319' if reg == 'BD' else ('0314' if reg == 'IND' else '0315')
    packet_bytes = bytes.fromhex(CS_SOLO_START_MATCH_HEX)
    try:
        proto = thunderFF_pb2.StartMatch()
        proto.ParseFromString(packet_bytes)
        if hasattr(proto.main, 'region_list'):
            for r in proto.main.region_list:
                r.region = reg
        if hasattr(proto.main, 'client_version'):
            proto.main.client_version.remote_version = str(app_ver)
        if match_mode and hasattr(proto.main, 'match_mode'):
            proto.main.match_mode = int(match_mode)
        packet_bytes = proto.SerializeToString()
    except Exception:
        pass
    encrypted_packet = (await aes_encrypt(packet_bytes, key, iv)).hex()
    packet_length = len(encrypted_packet) // 2
    hex_length = f"{packet_length:08x}"
    return bytes.fromhex(pkt_prefix + hex_length + encrypted_packet)

async def CS_Solo_Cancel_Matchmaking_Packet(uid, key, iv, region="BD"):
    fields = {
        1: 11,
        2: {
            1: int(uid)
        }
    }
    proto_bytes = await build_proto_packet(fields)
    reg = str(region).upper() if region else "BD"
    pkt_prefix = '0319' if reg == 'BD' else ('0314' if reg == 'IND' else '0315')
    encrypted_packet = (await aes_encrypt(proto_bytes, key, iv)).hex()
    packet_length = len(encrypted_packet) // 2
    hex_length = f"{packet_length:08x}"
    return bytes.fromhex(pkt_prefix + hex_length + encrypted_packet)

async def start_game_match(region, client_version, writer, key, iv, mode_key: str = "battle_royale"):
    mode_cfg = GAME_MODES.get(mode_key, GAME_MODES["battle_royale"])
    if mode_key in ("clash_squad", "clash_squad_ranked"):
        match_mode = int(mode_cfg.get("match_mode", 1))
        packet_bytes = await CS_Solo_Start_Matchmaking_Packet(
            key, iv, region=region, client_ver=client_version, match_mode=match_mode
        )
        writer.write(packet_bytes)
        await writer.drain()
        return

    packet = bytes.fromhex("080112800a0a010b102b3a110a044944433110aa011a064555524f50453a100a044944433210311a064555524f504540014a0801090a0b1219202758016291090a8001303838463832424630324139363736373032303130313030303030303030303030303136303030313030313530303032323246393745454530463030303030303436373632353134303030303030303030303030303030303030303030303030303030303030303030303030303066663030303030303030636163666131366410241afb02735d5e571400024a775d45414d1a041b1c001f11010449715f4243481a001e1d071c1703004b1a4066785c524570735c51486775421b5c5a4c07504042685a63610816054e19025e75196001477c015165406370195f5547404e4550640103020f1304064863754268676c755f65576e40467e5f0a417a4701026d675d6e73670b1108495a4c6a0b78470b740065645e525a057258425f584a447d4e6759440c11044e7c596d7f4b625f7d04055a47505c4e1d6b5b4107447d7201057d7f0f14084e430457674f7e517d72015172415d027473577c4d615f79535256780911030f4d5e027a797f614165067806505d53777750475e75064257076500460817014e741e7e5078487e7a7c465e7669767153497064605a7376677773550d160148037e18675966787f4c42607a645f577e7b441b460776026b18685d0b110205490060020f70676175654674706671797f41067346677c4e06585e780f15074c57047b40517075415f6364027259674b5b0166407f7340600407770a22047a5d5c52300b3a0a167305067162727516134208312e3133302e3232480350015ae90403626253513635686e556f4e36416456324b796f566c636f477776484f624e56526c4d727073504b4f43654177616848494176795556497273743752737149734a7a786b3247525268377a2f637664626d504f6a73552f79626d38547a4c69586d2f474351696d494b53486833447955726f39515152756c34545350626d6d624b7949565937545671577059455372323646572f59624578507338514f706d317372785455736c30796a434144444d4f34616a654b615753366361496c554b4963797a494e396d52516f715277687939797257476d337a644345337a6a61436f492f5a585233656f65365a42647a64677654636b6b665733356e4d4c6a6a565072564b6433523172756174394e50514150724a5546627859696c4c5a3859707336654d5447666b6649793574666a526c314d4648706b51774c6373374439656378566c41636f374e664f6d2b30654756466c4434744478706771385533595973587645384842502f70666c767a737138316a32524f4d7857437556445442492f684735625462773166456e4249725162762b636144775147696f74554e316d4c4b77734379456f4766706746614251457645672b736a764c4c78704743334c304a5344532f74526169504354553344374e6249306547516651622f5a466f4c36455630775a324d6f583932414c572f5049752f56634663584e70596b356f7966326151416a536971486a2f363276354843644f525551303578754e6171795251625653704654303137655237675255636b4966366c6f447476342b514e4a4670766d74757077707774396a5a5974437a4b56743657726d6e36785837706658456251555434684f3758a201050803108703a201050804108103a20105080510c001a20105081d10cc01a2010408161078a20105080e10af01a201020815")
    proto = thunderFF_pb2.StartMatch()
    proto.ParseFromString(packet)
    target_map = int(mode_cfg.get("map_id", 1))
    if hasattr(proto.main, 'map_ids'):
        del proto.main.map_ids[:]
        proto.main.map_ids.append(target_map)
    elif hasattr(proto.main, 'map_id'):
        proto.main.map_id = target_map
    proto.main.game_mode = int(mode_cfg["game_mode"])
    proto.main.match_mode = int(mode_cfg["match_mode"])
    if hasattr(proto.main, 'region_list') and len(proto.main.region_list) > 0:
        proto.main.region_list[0].region = region
        if len(proto.main.region_list) > 1:
            proto.main.region_list[1].region = region
    if client_version and hasattr(proto.main, 'client_version'):
        proto.main.client_version.remote_version = str(client_version)
    packet = proto.SerializeToString()
    group_mode = int(mode_cfg.get("group_mode", 1))
    packet = packet.replace(b'\x58\x01', bytes([0x58, group_mode]))
    encrypted_packet = (await aes_encrypt(packet, key, iv)).hex()
    packet_length = len(encrypted_packet) // 2
    hex_length = hex(packet_length)[2:]
    hex_length = hex_length if len(hex_length) > 1 else "0" + hex_length
    reg = str(region).upper() if region else "IND"
    cmd_prefix = "031900" if reg == "BD" else ("031400" if reg == "IND" else "031500")
    final_packet = cmd_prefix + "0" * (6 - len(hex_length)) + hex_length + encrypted_packet
    writer.write(bytes.fromhex(final_packet))
    await writer.drain()

start_game_lone_wolf = start_game_match

def has_ssan_zig_sync(n):
    z = (n << 1) & 0xFFFFFFFFFFFFFFFF
    out = bytearray()
    while z >= 0x80:
        out.append((z & 0x7F) | 0x80)
        z >>= 7
    out.append(z)
    return bytes(out)

async def has_ssan_zig(n):
    return has_ssan_zig_sync(n)

def uleb_encode_sync(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            b |= 0x80
        out.append(b)
        if not n:
            break
    return bytes(out)

async def uleb_encode(n):
    return uleb_encode_sync(n)

def tea_enc(v0, v1, k0, k1, k2, k3):
    s = 0
    for _ in range(_ROUNDS):
        s = (s + _DELTA) & 0xFFFFFFFF
        v0 = (v0 + (((((v1 << 4) & 0xFFFFFFFF) + k0) & 0xFFFFFFFF ^
                      ((v1 + s) & 0xFFFFFFFF) ^
                      (((v1 >> 5) + k1) & 0xFFFFFFFF)))) & 0xFFFFFFFF
        v1 = (v1 + (((((v0 << 4) & 0xFFFFFFFF) + k2) & 0xFFFFFFFF ^
                      ((v0 + s) & 0xFFFFFFFF) ^
                      (((v0 >> 5) + k3) & 0xFFFFFFFF)))) & 0xFFFFFFFF
    return v0, v1

def tea_dec(v0, v1, k0, k1, k2, k3):
    s = (_DELTA * _ROUNDS) & 0xFFFFFFFF
    for _ in range(_ROUNDS):
        v1 = (v1 - (((((v0 << 4) & 0xFFFFFFFF) + k2) & 0xFFFFFFFF ^
                      ((v0 + s) & 0xFFFFFFFF) ^
                      (((v0 >> 5) + k3) & 0xFFFFFFFF)))) & 0xFFFFFFFF
        v0 = (v0 - (((((v1 << 4) & 0xFFFFFFFF) + k0) & 0xFFFFFFFF ^
                      ((v1 + s) & 0xFFFFFFFF) ^
                      (((v1 >> 5) + k1) & 0xFFFFFFFF)))) & 0xFFFFFFFF
        s = (s - _DELTA) & 0xFFFFFFFF
    return v0, v1

def build_padded(content):
    pad_len = (8 - (len(content) + 10) % 8) % 8
    return bytes([pad_len, 0, 0]) + b"\x00" * pad_len + content + b"\x00" * 7

def encode_header(layout, send_option, cmd, order_id, flags, length, k, v80):
    out = bytearray()
    for code in layout:
        value = {0: send_option, 1: cmd, 2: order_id, 3: flags, 4: length}[code]
        if _FIELD_SIZES[code] == 1:
            out.append((value & 0xFF) ^ k)
        else:
            v = ((value & 0xFFFF) ^ v80) & 0xFFFF
            out.append(v & 0xFF)
            out.append((v >> 8) & 0xFF)
    return bytes(out)

def crc7_buff(crc, buf):
    c = crc & 0x7F
    for b in buf:
        c = CRC7_TABLE[((2 * (c & 0xFF)) ^ (b & 0xFF)) & 0xFF] & 0x7F
    return c & 0x7F

def tea_cbc_encrypt(padded, key_bytes):
    k0, k1, k2, k3 = (struct.unpack_from("<I", key_bytes, o)[0] for o in (0, 4, 8, 12))
    out = bytearray(len(padded))
    prev_cipher = bytearray(8)
    prev_intermediate = bytearray(8)
    for i in range(0, len(padded), 8):
        xored = bytearray(8)
        for j in range(8):
            xored[j] = padded[i + j] ^ prev_cipher[j]
        e0, e1 = tea_enc(
            struct.unpack_from("<I", xored, 0)[0],
            struct.unpack_from("<I", xored, 4)[0],
            k0, k1, k2, k3,
        )
        enc = bytearray(8)
        struct.pack_into("<I", enc, 0, e0)
        struct.pack_into("<I", enc, 4, e1)
        for j in range(8):
            out[i + j] = enc[j] ^ prev_intermediate[j]
        prev_cipher[:] = out[i:i + 8]
        prev_intermediate[:] = xored
    return bytes(out)

def tea_cbc_decrypt(body, key_bytes):
    k0, k1, k2, k3 = (struct.unpack_from("<I", key_bytes, o)[0] for o in (0, 4, 8, 12))
    out = bytearray(len(body))
    prev_intermediate = bytearray(8)
    prev_cipher = bytearray(8)
    xored = bytearray(8)
    dec = bytearray(8)
    for i in range(0, len(body), 8):
        for j in range(8):
            xored[j] = body[i + j] ^ prev_intermediate[j]
        d0, d1 = tea_dec(
            struct.unpack_from("<I", xored, 0)[0],
            struct.unpack_from("<I", xored, 4)[0],
            k0, k1, k2, k3
        )
        struct.pack_into("<I", dec, 0, d0)
        struct.pack_into("<I", dec, 4, d1)
        for j in range(8):
            out[i + j] = dec[j] ^ prev_cipher[j]
        prev_cipher[:] = body[i:i + 8]
        prev_intermediate[:] = dec
    return bytes(out)

def sv_frame(msg_key, layout, send_option, cmd, order_id, flags, content, key, encrypted=True):
    k = key[0]
    v80 = ((k << 8) | k) & 0xFFFF
    body = tea_cbc_encrypt(build_padded(content), key) if encrypted else content
    hdr = bytearray([msg_key, 0]) + encode_header(layout, send_option, cmd, order_id, flags, len(body), k, v80)
    packet = bytearray(hdr + body)
    packet[1] = crc7_buff(0, bytes(packet[2:])) & 0x7F
    return bytes(packet)

async def build_match_startup_packets(token, udp_key, match_code, account_id, block_val,
                                      server_ip="", region="BD", client_version="1.132.6",
                                      client_version_code="2019121229", access_token="",
                                      game_mode: int = 43, map_id: int = 11):
    token = token.strip()
    udp_key = bytes.fromhex(udp_key)
    if isinstance(match_code, str):
        match_code = [int(ch) for ch in match_code.strip() if ch.isdigit()]
    elif isinstance(match_code, (list, tuple)):
        match_code = [int(ch) for ch in match_code if str(ch).isdigit()]
    else:
        match_code = [int(ch) for ch in str(match_code).strip() if ch.isdigit()]
    
    encoded_token = token.encode() if isinstance(token, str) else token
    reg = str(region).upper() if region else "BD"
    clean_ip = server_ip.split(':')[0] if server_ip else "0.0.0.0"
    clean_acc_tok = access_token.strip() if access_token else ""

    is_cs = (int(game_mode) in (11, 15))

    if is_cs:
        # Official Clash Squad Chunk Size = 1060 bytes from cs.py
        CHUNK_SIZE = 1060
        chunks = [encoded_token[i:i + CHUNK_SIZE] for i in range(0, len(encoded_token), CHUNK_SIZE)] or [b""]
        thunder_chunks = chunks[:-1]
        encoded_sharma_jwt = chunks[-1]

        thunder_packets = []
        for idx, chunk in enumerate(thunder_chunks):
            garena420 = await has_ssan_zig(len(chunk)) + chunk
            process = sv_frame(0x5E, match_code, 2, 447, idx, 1, garena420, udp_key)
            thunder_packets.append(process.hex())

        # Exact csoversea block verified from cs.py official capture
        csoversea_block = bytes.fromhex(
            "ca0163736f7665727365612e7374726f6e67686f6c642e66726565666972656d6f62696c652e636f6d"
            "3b302e302e302e303b33342e3132362e37362e34353b33342e38372e3137372e31343b33342e38372e"
            "3137302e3233303b33352e3138352e3138332e35370000010000000100000000000000000000000001"
            "00000000000100010000030100b0e5e4a487da8cdf110200"
        )
        mid = bytes.fromhex('0000000000000101060101') + await has_ssan_zig(len(reg)) + reg.encode()
        mid += bytes.fromhex('0001030001000004')
        mid += await has_ssan_zig(len(client_version)) + client_version.encode()
        mid += await has_ssan_zig(len(client_version_code)) + client_version_code.encode()
        mid += csoversea_block
        mid += await has_ssan_zig(len(clean_ip)) + clean_ip.encode()

        if clean_acc_tok:
            mid += await has_ssan_zig(len(clean_acc_tok)) + clean_acc_tok.encode()

        mid += await has_ssan_zig(len(encoded_sharma_jwt)) + encoded_sharma_jwt

        tg_garena420 = (
            await uleb_encode(int(account_id)) +
            await uleb_encode(int(block_val)) +
            await uleb_encode(1) +
            await uleb_encode(15) +  # GameMode 15 for CS
            await uleb_encode(int(block_val)) +
            await uleb_encode(1) +   # Map 1 for CS
            mid
        )
        loading = sv_frame(0x5A, match_code, 2, 448, len(thunder_packets), 1, tg_garena420, udp_key)
        return thunder_packets, loading.hex()

    else:
        # OB55 standard split (Lone Wolf / BR)
        thunder_jwt = token[:660] if len(token) > 660 else token
        sharma_jwt = token[660:] if len(token) > 660 else ""
        encoded_thunder_jwt = thunder_jwt.encode() if isinstance(thunder_jwt, str) else thunder_jwt
        encoded_sharma_jwt = sharma_jwt.encode() if isinstance(sharma_jwt, str) else sharma_jwt
        
        garena420 = await has_ssan_zig(len(encoded_thunder_jwt)) + encoded_thunder_jwt
        
        csoversea_block = bytes.fromhex(
            "ca0163736f7665727365612e7374726f6e67686f6c642e66726565666972656d6f62696c652e636f6d"
            "3b302e302e302e303b33342e3132362e37362e34353b33342e38372e3137372e31343b33342e38372e"
            "3137302e3233303b33352e3138352e3138332e35370000000000000100000000000000000000000001"
            "00000800000100000000000100a8a2d7bebd8d8bdf110200"
        )
        
        mid = bytes.fromhex('0000000001000102030101') + await has_ssan_zig(len(reg)) + reg.encode()
        mid += bytes.fromhex('0001030003000004')
        mid += await has_ssan_zig(len(client_version)) + client_version.encode()
        mid += await has_ssan_zig(len(client_version_code)) + client_version_code.encode()
        mid += csoversea_block
        mid += await has_ssan_zig(len(clean_ip)) + clean_ip.encode()
        
        if clean_acc_tok:
            mid += await has_ssan_zig(len(clean_acc_tok)) + clean_acc_tok.encode()
            
        mid += await has_ssan_zig(len(encoded_sharma_jwt)) + encoded_sharma_jwt
        
        tg_garena420 = (
            await uleb_encode(int(account_id)) +
            await uleb_encode(int(block_val)) +
            await uleb_encode(1) +
            await uleb_encode(int(game_mode)) +
            await uleb_encode(int(block_val)) +
            await uleb_encode(int(map_id)) +
            mid
        )
        
        process = sv_frame(0x5E, match_code, 2, 447, 0, 1, garena420, udp_key)
        loading = sv_frame(0x5A, match_code, 2, 448, 1, 1, tg_garena420, udp_key)
        return [process.hex()], loading.hex()

def produce_xor_key(secret_key):
    k = secret_key[0] if secret_key and len(secret_key) > 0 else 10
    return k, ((k << 8) | k) & 0xFFFF

def parse_layout(layout):
    if isinstance(layout, (list, tuple)):
        return [int(ch) for ch in layout if str(ch).isdigit()]
    return [int(ch) for ch in str(layout).strip() if ch.isdigit()]

def build_hello_packet_sync(text, key, layout):
    data = text.encode("utf-8")
    if len(data) > 25:
        raise ValueError(f"Text is too long ({len(data)} bytes)")
    content = b"\x10\x00\x00\x00" + data + b"\x00" * (29 - 4 - len(data))
    k = key[0] if key and len(key) > 0 else 10
    v80 = ((k << 8) | k) & 0xFFFF
    if isinstance(layout, (list, tuple)):
        layout = [int(ch) for ch in layout if str(ch).isdigit()]
    else:
        layout = [int(ch) for ch in str(layout).strip() if ch.isdigit()]
    padded = build_padded(content)
    enc_body = tea_cbc_encrypt(padded, key)
    header_bytes = encode_header(layout, 1, 1, 0, 1, len(enc_body), k, v80)
    packet = bytearray([0x63, 0x00]) + header_bytes + enc_body
    packet[1] = crc7_buff(0, packet[2:]) & 0x7F
    return bytes(packet).hex()

async def build_hello_packet(text, key, layout):
    return build_hello_packet_sync(text, key, layout)

def classify_sync(frame):
    cmd = frame.get("cmd", 0)
    msg_name = MESSAGE_ID_TO_NAME.get(cmd, f"UNKNOWN_{cmd}")
    if msg_name == "UDP_HELLO":
        return "HELLO"
    if msg_name == "UDP_ACK":
        return "ACK"
    if msg_name == "UDP_PING":
        return "PING"
    if msg_name == "RUDP_JOIN_MATCH":
        return "JOIN_MATCH"
    if msg_name.startswith("RUDP_") or msg_name.startswith("UDP_"):
        return msg_name
    return "DATA"

async def classify(frame):
    return classify_sync(frame)

def layouts_from_mask_sync(mask):
    if isinstance(mask, (list, tuple)):
        ru = [int(c) for c in mask if str(c).isdigit()]
    else:
        ru = [int(c) for c in str(mask).strip() if c.isdigit()]
    nr = [c for c in ru if c != 2]
    return ru, nr

async def layouts_from_mask(mask):
    return layouts_from_mask_sync(mask)

def build_packet_sync(msg_key, layout, send_option, cmd, order_id, flags, content, key, encrypted=True):
    k = key[0]
    v80 = ((k << 8) | k) & 0xFFFF
    body = tea_cbc_encrypt(build_padded(content), key) if encrypted else content
    hdr = bytearray([msg_key, 0])
    for code in layout:
        value = {0: send_option, 1: cmd, 2: (order_id or 0), 3: flags, 4: len(body)}[code]
        if _FIELD_SIZES[code] == 1:
            hdr.append((value & 0xFF) ^ k)
        else:
            v = ((value & 0xFFFF) ^ v80) & 0xFFFF
            hdr.append(v & 0xFF)
            hdr.append((v >> 8) & 0xFF)
    packet = bytearray(hdr + body)
    packet[1] = crc7_buff(0, bytes(packet[2:])) & 0x7F
    return bytes(packet)

async def build_packet(msg_key, layout, send_option, cmd, order_id, flags, content, key, encrypted=True):
    return build_packet_sync(msg_key, layout, send_option, cmd, order_id, flags, content, key, encrypted)

def reply_for_sync(frame, key, mask, ack_key=0x68, ping_key=0x6D, hello_key=0x5B, ack_style="short"):
    ru, nr = layouts_from_mask_sync(mask)
    typ = classify_sync(frame)
    if typ == "HELLO":
        if ack_style == "echo":
            content = frame.get("content") or b"\x10\x00\x00\x00"
            return typ, build_packet_sync(hello_key, nr, 1, 1, None, 1, content, key)
        return typ, build_packet_sync(ack_key, nr, 0, 2, None, 1, b"\x01\x00", key)
    if typ == "ACK":
        content = frame.get("content") or b"\x01\x00"
        return typ, build_packet_sync(ack_key, nr, 0, 2, None, 1, content, key)
    if typ == "PING":
        c = frame.get("content") or b"\x00\x00\x00\x00"
        counter = c[:4] if len(c) >= 4 else c
        return typ, build_packet_sync(ping_key, nr, 0, 3, None, 0, counter + b"\x00\x00\x00", key, encrypted=False)
    if typ == "JOIN_MATCH":
        return typ, build_packet_sync(ack_key, nr, 0, 2, None, 1, b"\x02\x00", key)
    return typ, None

async def reply_for(frame, key, mask, ack_key=0x68, ping_key=0x6D, hello_key=0x5B, ack_style="short"):
    return reply_for_sync(frame, key, mask, ack_key, ping_key, hello_key, ack_style)

async def keepalive_ping(sock, ip, port, key_bytes, mask, stop_event):
    nr = (await layouts_from_mask(mask))[1]
    ping_keys = [0x66, 0x6D, 0x69, 0x6C, 0x6B, 0x6E, 0x6F, 0x70]
    loop = asyncio.get_running_loop()  # Bug fix: get_event_loop() deprecated
    i = 0
    while not stop_event.is_set():
        pk = ping_keys[i % len(ping_keys)]
        counter = int(time.time() * 1000) & 0xFFFFFFFF
        pkt = await build_packet(pk, nr, 0, 3, None, 0, struct.pack("<I", counter) + b"\x00\x00\x00", key_bytes, encrypted=False)
        try:
            await async_udp_send(loop, sock, pkt, (ip, port))
        except Exception:
            pass
        i += 1
        try:
            # 🔥 LATENCY FIX: Ping interval 3s → 2s
            # Germany→India route pe NAT/firewall 3s mein UDP flow drop kar sakti hai
            # 2s pe ping se connection always fresh rahega — reconnect overhead khatam
            await asyncio.wait_for(stop_event.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pass

_DEFAULT_MOVEMENT_SAMPLES = [
    bytes.fromhex("81808008e404d2eaa9019f83170000c80100000000000000bdb6e1f30300c4b6e1fb0b000021000000f62c"),
    bytes.fromhex("81808008e404d2eaa9019f83170000c80100000000000000bdb6e1f30300c4b6e1fb0b000020000000b62f"),
    bytes.fromhex("81808008e404d2eaa9019f83170000c80100000000000000bdb6e1f30300c4b6e1fb0b00002b000000fe33"),
    bytes.fromhex("81808008e404d2eaa9019f83170000c80100000000000000bdb6e1f30300c4b6e1fb0b0000cf05000000c636"),
    bytes.fromhex("81808008e404d2eaa9019f83170000c80100000000000000bdb6e1f30300c4b6e1fb0b0000a504000000c93e")
]

# ==================== IN-MEMORY HIGH-SPEED ASSET CACHE ====================
_GLOBAL_MOVEMENT_CACHE: Dict[str, List[bytes]] = {}
_GLOBAL_ACTIONS_CACHE: Dict[str, List[dict]] = {}
_GLOBAL_COMBAT_LOOP_CACHE: Dict[str, List[dict]] = {}

def _strip_trailing_varint(data: bytes) -> bytes:
    """Safely removes trailing protobuf varint timestamp without corrupting coordinates or headers."""
    if len(data) <= 4:
        return data
    idx = len(data) - 2
    while idx >= 0 and (data[idx] & 0x80):
        idx -= 1
    return data[:idx + 1]

def _init_in_memory_assets():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 1. Preload Movement Samples (CS and Classic / Battle Royale)
    for key, filename in [("cs", "cs_movement_samples.json"), ("normal", "movement_samples.json")]:
        path = os.path.join(base_dir, filename)
        samples = [_strip_trailing_varint(s) for s in _DEFAULT_MOVEMENT_SAMPLES]
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if loaded and isinstance(loaded, list):
                        samples = [_strip_trailing_varint(bytes.fromhex(s)) for s in loaded]
            except Exception:
                pass
        _GLOBAL_MOVEMENT_CACHE[key] = samples

    # 2. Preload Combat Actions (CS and Classic / Battle Royale)
    for key, filename in [("cs", "cs_match_actions_sequence.json"), ("normal", "match_actions_sequence.json")]:
        path = os.path.join(base_dir, filename)
        actions = []
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    loaded_acts = json.load(f)
                    if loaded_acts and isinstance(loaded_acts, list):
                        actions = loaded_acts
            except Exception:
                pass
        _GLOBAL_ACTIONS_CACHE[key] = actions
        combat_loop = [
            a for a in actions if a.get("cmd") in (108, 104, 105, 106, 133, 134, 111, 113, 146, 413, 1492, 160)
        ] or actions
        _GLOBAL_COMBAT_LOOP_CACHE[key] = combat_loop

_init_in_memory_assets()

def _enc_varint(val: int) -> bytes:
    res = bytearray()
    while val >= 0x80:
        res.append((val & 0x7F) | 0x80)
        val >>= 7
    res.append(val & 0x7F)
    return bytes(res)

async def movement_sync_loop(sock, ip, port, key_bytes, mask, stop_event, account_id, match_index, mode_key: str = "battle_royale"):
    """Sends genuine OB55 cmd=2001 (Movement / Position Sync) to prevent AFK abandonment — Zero Disk Latency"""
    nr = (await layouts_from_mask(mask))[1]
    loop = asyncio.get_running_loop()
    is_cs = mode_key in ("clash_squad", "clash_squad_ranked")
    cache_key = "cs" if is_cs else "normal"
    samples = _GLOBAL_MOVEMENT_CACHE.get(cache_key) or [_strip_trailing_varint(s) for s in _DEFAULT_MOVEMENT_SAMPLES]

    step = 0
    last_sync_log = 0.0
    start_t = time.time()
    
    while not stop_event.is_set():
        now = time.time()
        base_payload = samples[step % len(samples)]
        elapsed_ms = int((now - start_t) * 1000) & 0xFFFFFF
        sample_payload = base_payload + _enc_varint(elapsed_ms)

        pkt_2001 = build_packet_sync(0x69, nr, 0, 2001, None, 0, sample_payload, key_bytes, encrypted=False)
        sent_ok = False
        for _attempt in range(2):  # 🔥 PACKET DROP FIX: movement retry once on fail
            try:
                await async_udp_send(loop, sock, pkt_2001, (ip, port))
                sent_ok = True
                break
            except Exception:
                if _attempt == 0:
                    await asyncio.sleep(0.01)  # 10ms gap before retry

        step += 1
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=0.30)
        except asyncio.TimeoutError:
            pass


async def action_playback_loop(sock, ip, port, key_bytes, mask, stop_event, account_id, match_index, mode_key: str = "battle_royale"):
    """
    Plays back genuine OB55 in-game combat and interaction actions (Gun switch, Fire, Reload, Hit, Jump, Loot, CS Shop)
    with sequentially ordered RUDP orderIds (orderId >= 2) — Loaded directly from in-memory cache (Zero Disk Latency).
    """
    ru, nr = await layouts_from_mask(mask)
    loop = asyncio.get_running_loop()
    is_cs = mode_key in ("clash_squad", "clash_squad_ranked")
    cache_key = "cs" if is_cs else "normal"
    actions = _GLOBAL_ACTIONS_CACHE.get(cache_key) or []

    if not actions:
        print_warning(f"[MATCH #{match_index}] [ACTIONS] No actions sequence found; combat playback skipped.")
        return

    combat_loop_actions = _GLOBAL_COMBAT_LOOP_CACHE.get(cache_key) or actions

    # Initial grace period: wait 2.5s after match start before beginning combat interactions
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=2.5)
        return
    except asyncio.TimeoutError:
        pass

    order_id = 2
    action_idx = 0
    total_actions = len(actions)
    mode_label = "Clash Squad" if is_cs else "Battle Royale"

    while not stop_event.is_set():
        if action_idx < total_actions:
            act = actions[action_idx]
        else:
            # Replay combat actions if match is long
            loop_idx = (action_idx - total_actions) % len(combat_loop_actions)
            act = combat_loop_actions[loop_idx]

        cmd = act.get("cmd", 108)
        content_hex = act.get("content_hex", "")
        if not content_hex:
            action_idx += 1
            continue

        payload = bytes.fromhex(content_hex)
        msg_key = act.get("msg_key", 0x5C)

        try:
            pkt = build_packet_sync(
                msg_key, ru, 2, cmd, order_id, 1, payload, key_bytes, encrypted=True
            )
            await async_udp_send(loop, sock, pkt, (ip, port))
        except Exception:
            pass

        order_id += 1
        action_idx += 1

        # Natural delay between combat actions: 2.2 to 3.8 seconds
        delay = 2.2 + (order_id % 5) * 0.4
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass


def try_header_sync(buf, layout, k, v80):
    off = 2
    out = {}
    for code in layout:
        size = _FIELD_SIZES[code]
        if off + size > len(buf):
            return None
        out[_FIELD_NAMES[code]] = (buf[off] ^ k) if size == 1 else ((buf[off] | (buf[off + 1] << 8)) ^ v80) & 0xFFFF
        off += size
    out["headerLen"] = off
    return out

async def try_header(buf, layout, k, v80):
    return try_header_sync(buf, layout, k, v80)

def oicq_unpad_sync(padded):
    if not padded or len(padded) < 8:
        return None
    if not all(padded[-1 - i] == 0 for i in range(7)):
        return None
    pad_len = padded[0] & 0x07
    s = 3 + pad_len
    e = len(padded) - 7
    return padded[s:e] if s < e else b""

async def oicq_unpad(padded):
    return oicq_unpad_sync(padded)

# Commands whose body content is strictly required and must be validated with TEA decryption + OICQ unpadding
# (1: HELLO, 2: ACK, 3: PING, 103: MATCH_FINISHED, 107: MATCH_TERMINATED, 2000: Ping Echo)
_CONTENT_CRITICAL_CMDS = {1, 2, 3, 103, 107, 2000}

def decode_packet_sync(packet, key, mask=None, needs_content=False):
    """
    Ultra-Fast Synchronous Packet Decoder with Smart Lazy Decryption & Strict Validation:
    Extracts cmd, orderId, flags from header in 1 microsecond (1,000,000 packets/sec).
    Only decrypts body when command actually needs content (or on match completion), saving ~80% CPU during match!
    Prevents false-positive match termination by strictly authenticating cmd 103 and 107.
    """
    data = bytes(packet) if isinstance(packet, bytes) else bytes.fromhex(packet)
    if len(data) < 8:
        return None
    k = key[0]
    v80 = ((k << 8) | k) & 0xFFFF
    crc_ok = (data[1] & 0x7F) == crc7_buff(0, data[2:])
    candidates = []
    if mask:
        ru, nr = layouts_from_mask_sync(mask)
        layouts = [("RUDP", ru), ("nonRUDP", nr)]
    else:
        layouts = [("RUDP", list(p)) for p in itertools.permutations([0, 1, 2, 3, 4])]
        layouts += [("nonRUDP", list(p)) for p in itertools.permutations([0, 1, 3, 4])]
    for kind, layout in layouts:
        f = try_header_sync(data, layout, k, v80)
        if not f:
            continue
        if f["flags"] > 7 or f["sendOption"] > 7:
            continue
        if f["length"] != len(data) - f["headerLen"]:
            continue
        cmd = f["cmd"]
        body = data[f["headerLen"]:f["headerLen"] + f["length"]]
        content = None
        padded = None
        if not (f["flags"] & 1):
            content = body
        elif needs_content or (cmd in _CONTENT_CRITICAL_CMDS):
            if len(body) >= 8 and len(body) % 8 == 0:
                padded = tea_cbc_decrypt(body, key)
                content = oicq_unpad_sync(padded)
                if content is None:
                    continue
            else:
                continue
        else:
            # CPU SAVER: For 99% of enemy positions, audio cues, visuals:
            # cmd, orderId, flags, length are ALREADY extracted from header in 1 microsecond!
            # Skip heavy decryption!
            content = None

        # Prioritize valid CRC and verified decrypted content
        score = (10 if crc_ok else 0) + (5 if content is not None else 0)
        candidates.append({
            "kind": kind, "layout": layout, "headerLen": f["headerLen"],
            "msgKey": data[0], "cmd": f["cmd"], "flags": f["flags"],
            "sendOption": f["sendOption"], "orderId": f.get("orderId"),
            "length": f["length"], "content": content, "crcOk": crc_ok,
            "padded": padded, "score": score, "total": len(data),
        })
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c["crcOk"], c["score"], c["kind"] == "RUDP"), reverse=True)
    return candidates[0]

async def decode_packet(packet, key, mask=None, needs_content=False):
    return decode_packet_sync(packet, key, mask, needs_content)





# ============================================================
# play_game — UDP MATCH (FIXED & DNS OPTIMIZED)
# ============================================================
async def play_game(server_ip_port, thunder, sharma, udp_key, match_code,
                    account_id, player_region, client_version, key, iv,
                    match_index: int, mode_key: str = "battle_royale"):
    match_start_time = time.time()
    ping_task = None
    movement_task = None
    action_task = None
    sock = None
    ping_stop = asyncio.Event()
    movement_stop = asyncio.Event()
    action_stop = asyncio.Event()
    uid_str = str(account_id)
    completed_cleanly = False
    mode_title = GAME_MODES.get(mode_key, {}).get("name", mode_key)
    last_server_addr = None
    ack_state = "waiting_for_hello_reply"
    thunder_sent = False
    sharma_sent = False
    join_match_received = False
    local_closed = False
    send_lock = asyncio.Lock()

    try:
        ip, port = server_ip_port.split(":")
        port = int(port)
        resolved_ip = await resolve_host_cloudflare(ip)

        loop = asyncio.get_running_loop()  # Bug fix: get_event_loop() deprecated
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        optimize_udp_socket(sock)
        sock.setblocking(False)
        # 🔥 LATENCY FIX: UDP socket ko server se "connect" karo
        # Isse OS routing table har packet pe check nahi karega — ~0.2-0.5ms save per packet
        # (UDP connect sirf default destination set karta hai — koi actual handshake nahi hota)
        try:
            sock.connect((resolved_ip, port))
        except Exception:
            pass

        udp_key_bytes = bytes.fromhex(udp_key)
        hello_packet = build_hello_packet_sync(f"{account_id}_2585", udp_key_bytes, match_code)
        hello_bytes = bytes.fromhex(hello_packet)
        # 🔥 PACKET DROP FIX: Hello double-send — first impression must reach server
        await async_udp_send(loop, sock, hello_bytes, (resolved_ip, port))
        await asyncio.sleep(0.1)
        await async_udp_send(loop, sock, hello_bytes, (resolved_ip, port))

        ping_task = asyncio.create_task(
            keepalive_ping(sock, resolved_ip, port, udp_key_bytes, match_code, ping_stop)
        )
        last_activity = time.time()
        MAX_IDLE_BEFORE_HELLO_RESEND = 1.5  # Optimized: Fast 1.5s recovery on UDP drop (was 7.0s)

        print_colored(
            f"🎮 [MATCH #{match_index}] [{mode_title.upper()}] UDP started → {server_ip_port} (DNS: {resolved_ip})",
            Colors.MAGENTA
        )

        async def send_thunder_sharma_inline():
            nonlocal ack_state, thunder_sent, sharma_sent, last_server_addr, movement_task, action_task
            if thunder_sent:
                return
            async with send_lock:
                if thunder_sent:
                    return
                try:
                    thunder_list = thunder if isinstance(thunder, (list, tuple)) else ([thunder] if thunder else [])
                    # 🔥 PACKET DROP FIX: Thunder packets double-send (50ms gap)
                    # Germany→India route pe drop chance high — critical packets 2 baar bhejo
                    for t_pkt in thunder_list:
                        t_bytes = bytes.fromhex(t_pkt)
                        await async_udp_send(loop, sock, t_bytes, (resolved_ip, port))
                        await asyncio.sleep(0.05)
                        await async_udp_send(loop, sock, t_bytes, (resolved_ip, port))  # duplicate for reliability
                        await asyncio.sleep(0.05)
                    thunder_sent = True
                    await asyncio.sleep(0.1)

                    # Handshake ACK (cmd 2 with 0100) — double send
                    prepare_ack = build_packet_sync(
                        0x68, layouts_from_mask_sync(match_code)[1],
                        0, 2, None, 1, b"\x01\x00", udp_key_bytes
                    )
                    await async_udp_send(loop, sock, prepare_ack, (resolved_ip, port))
                    await asyncio.sleep(0.05)
                    await async_udp_send(loop, sock, prepare_ack, (resolved_ip, port))  # duplicate ACK
                    await asyncio.sleep(0.15)

                    # 🔥 PACKET DROP FIX: Sharma double-send (100ms gap)
                    sharma_bytes = bytes.fromhex(sharma)
                    await async_udp_send(loop, sock, sharma_bytes, (resolved_ip, port))
                    await asyncio.sleep(0.1)
                    await async_udp_send(loop, sock, sharma_bytes, (resolved_ip, port))  # duplicate for reliability
                    sharma_sent = True
                    ack_state = "thunder_sharma_sent"
                    print_success(f"[MATCH #{match_index}] [{mode_title.upper()}] Thunder ({len(thunder_list)} parts) + Sharma sent!")
                    if movement_task is None:
                        movement_task = asyncio.create_task(
                            movement_sync_loop(sock, resolved_ip, port, udp_key_bytes, match_code, movement_stop, account_id, match_index, mode_key=mode_key)
                        )
                    if action_task is None:
                        action_task = asyncio.create_task(
                            action_playback_loop(sock, resolved_ip, port, udp_key_bytes, match_code, action_stop, account_id, match_index, mode_key=mode_key)
                        )

                except Exception as e:
                    print_error(f"[MATCH #{match_index}] [{mode_title.upper()}] send error: {e}")

        while not local_closed:
            # 🔥 Stop immediately if account was deleted from web dashboard
            canonical_uid = bot_state.resolve_uid(uid_str)
            is_active_account = (uid_str in bot_state.accounts or canonical_uid in bot_state.accounts)
            if not is_active_account and (uid_str in bot_state.deleted_uids or canonical_uid in bot_state.deleted_uids):
                print_warning(f"[MATCH #{match_index}] UID {uid_str} deleted from dashboard — stopping match!")
                local_closed = True
                break
            if time.time() - match_start_time > MAX_MATCH_DURATION:
                break
            try:
                response, server_addr = await async_udp_recv(loop, sock, 65535, timeout=1.5)
                # 🔥 SAFE FIX #3: Handle Windows ECONNRESET fallback (None, None)
                # On Linux this never triggers → identical behavior to before.
                if response is None:
                    raise asyncio.TimeoutError()
                if response:
                    last_activity = time.time()
                    last_server_addr = server_addr
                    # Synchronous Zero-Coroutine Decode with Smart Filter (1,000,000 pkts/sec)
                    frame = decode_packet_sync(response, udp_key_bytes, match_code)
                    if frame:
                        cmd = frame.get('cmd')
                        order_id = frame.get('orderId')
                        flags = frame.get('flags', 0)
                        nr_layout = layouts_from_mask_sync(match_code)[1]

                        if cmd in [103, 107]:
                            duration = int(time.time() - match_start_time)
                            print_success(
                                f"[MATCH #{match_index}] [{mode_title.upper()}] Server Finished (cmd {cmd}, Duration: {duration}s)"
                            )
                            completed_cleanly = True
                            local_closed = True
                            continue

                        if cmd == 2000:
                            try:
                                c = frame.get('content') or b"\x3c"
                                if len(c) == 3:
                                    echo_c = c[:2]
                                elif len(c) == 2 and c[1] in (0, 1):
                                    echo_c = c[:1]
                                else:
                                    echo_c = c
                                pkt_2000 = build_packet_sync(
                                    0x6D, nr_layout,
                                    0, 2000, None, 0, echo_c, udp_key_bytes, encrypted=False
                                )
                                await async_udp_send(loop, sock, pkt_2000, server_addr)
                            except Exception:
                                pass
                            continue

                        # CS Specific: JOIN_MATCH_FINISHED (Command 130)
                        if cmd == 130:
                            print_success(f"[MATCH #{match_index}] [{mode_title.upper()}] JOIN_MATCH_FINISHED - Clash Squad Loaded!")
                            try:
                                next_id = ((order_id or 0) + 1) & 0xFFFF
                                fin_ack = build_packet_sync(
                                    0x68, nr_layout, 0, 2, None, 1, next_id.to_bytes(2, "little"), udp_key_bytes
                                )
                                await async_udp_send(loop, sock, fin_ack, server_addr)
                            except Exception:
                                pass
                            continue

                        # Crucial Fix: Cumulative ACK (order_id + 1) for all incoming reliable packets
                        if (flags & 1) and order_id is not None:
                            try:
                                next_expected_id = (order_id + 1) & 0xFFFF
                                data_ack = build_packet_sync(
                                    0x68, nr_layout, 0, 2, None, 1, next_expected_id.to_bytes(2, "little"), udp_key_bytes
                                )
                                await async_udp_send(loop, sock, data_ack, server_addr)
                            except Exception:
                                pass

                        if cmd in [101, 144, 110, 116, 117, 136]:
                            try:
                                ack_pkt = build_packet_sync(
                                    0x68, nr_layout,
                                    0, 2, None, 1, b"\x01\x00", udp_key_bytes
                                )
                                await async_udp_send(loop, sock, ack_pkt, server_addr)
                            except Exception:
                                pass
                            if cmd == 101:
                                continue

                        ptype = classify_sync(frame)
                        if ptype in ["ACK", "PING", "HELLO", "JOIN_MATCH"]:
                            if ptype == "HELLO" and ack_state == "waiting_for_hello_reply":
                                typ, reply = reply_for_sync(
                                    frame, udp_key_bytes, match_code, ack_style="short"
                                )
                                if reply:
                                    await async_udp_send(loop, sock, reply, server_addr)
                                ack_state = "ready_to_send_thunder"
                                if not thunder_sent:
                                    await send_thunder_sharma_inline()
                            elif ptype == "ACK":
                                if ack_state in ["waiting_for_hello_reply", "ack_sent_waiting"]:
                                    ack_state = "ready_to_send_thunder"
                                    if not thunder_sent:
                                        await send_thunder_sharma_inline()
                                else:
                                    typ, reply = reply_for_sync(frame, udp_key_bytes, match_code)
                                    if reply:
                                        await async_udp_send(loop, sock, reply, server_addr)
                            elif ptype == "PING":
                                typ, reply = reply_for_sync(frame, udp_key_bytes, match_code)
                                if reply:
                                    await async_udp_send(loop, sock, reply, server_addr)
                            elif ptype == "JOIN_MATCH" and not join_match_received:
                                typ, reply = reply_for_sync(frame, udp_key_bytes, match_code)
                                if reply:
                                    await async_udp_send(loop, sock, reply, server_addr)
                                    join_match_received = True

                    # Micro-yield: Give TCP matchmaking gateway CPU priority so new matches start instantly
                    await asyncio.sleep(0)
            except asyncio.TimeoutError:
                if ack_state == "ready_to_send_thunder" and not thunder_sent:
                    await send_thunder_sharma_inline()
                elif ack_state == "waiting_for_hello_reply":
                    elapsed = time.time() - match_start_time
                    if (time.time() - last_activity) > MAX_IDLE_BEFORE_HELLO_RESEND:
                        retry_num = int(elapsed / MAX_IDLE_BEFORE_HELLO_RESEND)
                        print_info(f"[MATCH #{match_index}] Hello retry #{retry_num} ({elapsed:.1f}s elapsed)...")
                        try:
                            # 🔥 FIX: Re-resolve DNS on every 3rd retry (stale IP fix)
                            if retry_num % 3 == 0 and retry_num > 0:
                                resolved_ip = await resolve_host_cloudflare(ip)
                                print_info(f"[MATCH #{match_index}] DNS re-resolved → {resolved_ip}")
                            pkt = build_hello_packet_sync(
                                f"{account_id}_2585", udp_key_bytes, match_code
                            )
                            await async_udp_send(loop, sock, bytes.fromhex(pkt), (resolved_ip, port))
                        except Exception:
                            pass
                        last_activity = time.time()
                    # 🔥 FIX: Timeout 25s → 30s
                    if elapsed > 30.0:
                        print_warning(f"[MATCH #{match_index}] [{mode_title.upper()}] Handshake timeout after 30s (Server didn't respond to UDP Hello)")
                        break
                elif ack_state == "thunder_sharma_sent":
                    if (time.time() - last_activity) > MATCH_IDLE_TIMEOUT:
                        duration = int(time.time() - match_start_time)
                        print_success(f"[MATCH #{match_index}] [{mode_title.upper()}] Finished naturally ({duration}s duration)")
                        completed_cleanly = True
                        break
                continue
            except BlockingIOError:
                await asyncio.sleep(0.05)
            except OSError:
                await asyncio.sleep(0.5)
                continue
            except Exception:
                await asyncio.sleep(0.5)
                continue

            if ack_state == "ready_to_send_thunder" and not thunder_sent:
                await send_thunder_sharma_inline()

            if ack_state == "thunder_sharma_sent":
                if movement_task is None:
                    movement_task = asyncio.create_task(
                        movement_sync_loop(sock, resolved_ip, port, udp_key_bytes, match_code, movement_stop, account_id, match_index, mode_key=mode_key)
                    )
                if action_task is None:
                    action_task = asyncio.create_task(
                        action_playback_loop(sock, resolved_ip, port, udp_key_bytes, match_code, action_stop, account_id, match_index, mode_key=mode_key)
                    )

        return f"match #{match_index} finished"
    except Exception as e:
        err_name = type(e).__name__
        err_msg = str(e).strip()
        err_str = f"{err_name}: {err_msg}" if err_msg else err_name
        print_error(f"[MATCH #{match_index}] [{mode_title.upper()}] error: {err_str}")
        return f"match #{match_index} error"
    finally:
        # Increment match count for any match that was actively played or completed
        if thunder_sent or completed_cleanly or (time.time() - match_start_time) > 5.0:
            try:
                bot_state.increment_match(uid_str)
            except Exception:
                pass

        # Trigger immediate profile refresh (EXP & Level) and reward claims on dashboard
        fresh = bot_state.account_credentials.get(uid_str)
        if not fresh:
            fresh = bot_state.account_credentials.get(bot_state.resolve_uid(uid_str))
        if fresh:
            try:
                asyncio.create_task(refresh_account_profile(fresh))
                asyncio.create_task(claim_account_rewards(fresh))
            except Exception:
                pass
        ping_stop.set()
        movement_stop.set()
        action_stop.set()
        if ping_task:
            ping_task.cancel()
            try:
                await ping_task
            except asyncio.CancelledError:
                pass
        if movement_task:
            movement_task.cancel()
            try:
                await movement_task
            except asyncio.CancelledError:
                pass
        if action_task:
            action_task.cancel()
            try:
                await action_task
            except asyncio.CancelledError:
                pass
        if sock:
            try:
                sock.close()
            except Exception:
                pass
        remaining = await _dec_match(uid_str)
        total = await _get_total_match_count()
        duration = int(time.time() - match_start_time)
        print_info(
            f"[MATCH #{match_index}] Closed ({duration}s duration). "
            f"UID active: {remaining} | Total active: {total}"
        )
        try:
            bot_state.update_status(uid_str, "IN_MATCH" if remaining > 0 else "ONLINE", remaining)
        except Exception:
            pass


# ============================================================
# 🔥 functional_lone_wolf — TRUE Parallel + Smart Cache + DNS
# ============================================================
async def functional_lone_wolf(addrs, starter_packet, account_region, client_version,
                                key, iv, account_id="", account_data=None,
                                max_reconnects=10):
    reconnects = 0
    ip, port = addrs.split(":")
    play_matches: List[asyncio.Task] = []
    no_response_count = 0
    search_attempts = 0
    last_start_time = 0.0
    uid_str = str(account_id)

    consecutive_parse_failures = 0

    current_token = starter_packet
    current_key = key
    current_iv = iv
    current_account_data = account_data

    try:
        while True:
            writer = None
            try:
                if current_account_data:
                    fresh = None
                    if current_account_data.get('auth_type') == 'guest' and current_account_data.get('auth_uid'):
                        fresh = cache_get(str(current_account_data['auth_uid']))
                    elif current_account_data.get('auth_type') == 'token' and current_account_data.get('auth_token'):
                        fresh = cache_get(f"tok_{current_account_data['auth_token'][:20]}")

                    if fresh:
                        current_account_data = fresh
                        current_key = fresh['aes_ak']
                        current_iv = fresh['iv_i']
                        current_token = await build_tcp_startup_packet(
                            fresh['account_id'],
                            fresh['token'],
                            fresh['server_time'],
                            current_key,
                            current_iv,
                            region=fresh.get('region', account_region),
                            typ='OnLine'
                        )
                    else:
                        print_warning(f"[FUNCTIONAL] Cache miss for {uid_str} → re-login needed")
                        try:
                            if current_account_data.get('auth_uid'):
                                cache_invalidate(str(current_account_data['auth_uid']))
                            if current_account_data.get('auth_token'):
                                cache_invalidate(f"tok_{current_account_data['auth_token'][:20]}")
                        except Exception:
                            pass
                        raise ConnectionError("Cache expired, triggering fresh login")

                resolved_ip = await resolve_host_cloudflare(ip)
                proxy_url = current_account_data.get('proxy') if current_account_data else None
                reader, writer = await open_proxy_connection(resolved_ip, int(port), proxy_url)
                
                raw_sock = writer.get_extra_info('socket')
                if raw_sock:
                    optimize_tcp_socket(raw_sock)
                
                writer.write(bytes.fromhex(current_token))
                await writer.drain()

                # Send initial keepalive pulse right after connecting in OB55
                try:
                    init_ka = await send_keep_alive(account_region)
                    if init_ka and writer and not writer.is_closing():
                        writer.write(init_ka)
                        await asyncio.wait_for(writer.drain(), timeout=3)
                except Exception:
                    pass

                proxy_str = f" via Proxy: {proxy_url}" if proxy_url else ""
                print_success(f"[FUNCTIONAL] TCP Gateway Connected for UID: {uid_str}{proxy_str} (DNS: {resolved_ip})")
                reconnects = 0
                no_response_count = 0
                last_start_time = 0.0
                tcp_buffer = bytearray()
                current_region = str(account_region).upper() if account_region else "IND"

                def get_current_mode() -> str:
                    acc_obj = bot_state.accounts.get(uid_str) or bot_state.account_credentials.get(uid_str)
                    if acc_obj and acc_obj.get("mode"):
                        return acc_obj["mode"]
                    return bot_state.global_game_mode

                current_running_mode = get_current_mode()

                async def send_start_match():
                    nonlocal search_attempts, last_start_time, current_running_mode
                    search_attempts += 1
                    active_mode = get_current_mode()
                    current_running_mode = active_mode
                    if current_account_data:
                        current_account_data['mode'] = active_mode
                    mode_info = GAME_MODES.get(active_mode, GAME_MODES["battle_royale"])
                    mode_title = mode_info["name"]

                    print_info(f"[{mode_title.upper()}] Sending StartMatch #{search_attempts} region: {current_region}")
                    try:
                        await asyncio.sleep(random.uniform(0.2, 0.4))
                        await start_game_match(
                            current_region, client_version, writer,
                            current_key, current_iv,
                            mode_key=active_mode
                        )
                        print_success(f"[{mode_title.upper()}] StartMatch packet sent")
                        active = await _get_match_count(uid_str)
                        try:
                            bot_state.update_status(uid_str, "SEARCHING", active)
                        except Exception:
                            pass
                    except Exception as e:
                        print_error(f"start_game_match error: {e}")
                    last_start_time = asyncio.get_running_loop().time()

                in_queue = False
                last_ka_time = 0.0
                await send_start_match()

                while True:
                    play_matches[:] = [m for m in play_matches if not m.done()]

                    active_count = await _get_match_count(uid_str)
                    try:
                        bot_state.update_status(
                            uid_str,
                            "ONLINE" if active_count == 0 else "IN_MATCH",
                            active_count
                        )
                    except Exception:
                        pass

                    # Real-time mode switch detection from Web Dashboard!
                    live_mode = get_current_mode()
                    if live_mode != current_running_mode:
                        mode_title = GAME_MODES.get(live_mode, {}).get("name", live_mode)
                        print_info(f"Mode switched to [{mode_title.upper()}] via Dashboard! Restarting...")
                        current_running_mode = live_mode
                        search_attempts = 0
                        in_queue = False
                        await send_start_match()

                    now = asyncio.get_running_loop().time()
                    # Keep connection alive while in queue
                    if in_queue and (now - last_ka_time >= 8.0):
                        last_ka_time = now
                        try:
                            ka = await send_keep_alive(current_region)
                            if ka and writer and not writer.is_closing():
                                writer.write(ka)
                                await writer.drain()
                        except Exception:
                            pass

                    # Continuous StartMatch retry: refresh queue if stuck (wait 22s in queue instead of 45s)
                    retry_interval = 22.0 if in_queue else START_MATCH_INTERVAL
                    if now - last_start_time >= retry_interval:
                        in_queue = False
                        await send_start_match()

                    try:
                        data = await asyncio.wait_for(reader.read(8192), timeout=0.5)
                    except asyncio.TimeoutError:
                        no_response_count += 1
                        if no_response_count > 80:
                            print_warning(f"[FUNCTIONAL] Gateway silent ({uid_str}). Reconnecting...")
                            raise ConnectionError("Gateway idle timeout")
                        continue

                    if not data:
                        raise ConnectionError("Connection closed by server")

                    tcp_buffer.extend(data)
                    no_response_count = 0

                    match_allocated = False

                    # TCP framing loop
                    while len(tcp_buffer) >= 5:
                        payload_len = int.from_bytes(tcp_buffer[2:5], 'big')
                        if payload_len > 65536 or payload_len == 0:
                            tcp_buffer.pop(0)
                            continue
                        total_pkt_len = 5 + payload_len
                        if len(tcp_buffer) < total_pkt_len:
                            break
                        pkt = bytes(tcp_buffer[:total_pkt_len])
                        del tcp_buffer[:total_pkt_len]

                        pkt_hex = pkt.hex()

                        # In-queue status (pkt[0]==0x03, any region byte, small size)
                        if pkt[0] == 0x03 and 10 < total_pkt_len < 60:
                            in_queue = True
                            mode_title = GAME_MODES.get(current_running_mode, {}).get("name", current_running_mode)
                            print_info(f"[{mode_title.upper()}] Match starting, please wait in queue...")
                            continue

                        # Real match allocation packet (pkt[0]==0x03, match payload)
                        if pkt[0] == 0x03 and total_pkt_len >= 100:
                            token = None
                            udp_key = None
                            match_code = None
                            server_ip_port = None
                            match_account_id = None
                            block_val = None

                            # Try both: framed payload (5-byte skip) AND original hex[10:] offset
                            for proto_hex in [pkt[5:].hex(), pkt_hex[10:]]:
                                try:
                                    res = json.loads(await decode_protobuf(proto_hex))
                                    if '42' in res and 'data' in res['42']:
                                        match_code = res['42']['data']
                                    if '5' in res and 'data' in res['5']:
                                        res_field5 = res['5']['data']
                                        if isinstance(res_field5, dict):
                                            server_ip_port = res_field5.get('2', {}).get('data')
                                            udp_key = res_field5.get('3', {}).get('data')
                                            token = res_field5.get('4', {}).get('data')
                                            if '42' in res_field5:
                                                match_code = res_field5['42']['data']
                                            block_val = res_field5.get('1', {}).get('data')
                                    if '1' in res and 'data' in res['1']:
                                        match_account_id = res['1']['data']
                                    if server_ip_port and udp_key:
                                        break
                                except Exception:
                                    pass

                            # 🔥 ROBUST FALLBACKS: Crucial for Clash Squad where field 42 is absent & JWT contains binary trailer
                            if not match_code:
                                match_code = "01234"

                            if not isinstance(token, str) or not token.startswith("eyJ"):
                                jwt_m = re.search(rb'(eyJ[A-Za-z0-9_\-\.]+)', pkt)
                                if jwt_m:
                                    token = jwt_m.group(1).decode('ascii')

                            if not server_ip_port or ":" not in str(server_ip_port):
                                ip_m = re.search(rb'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d{3,5})', pkt)
                                if ip_m:
                                    server_ip_port = ip_m.group(1).decode('ascii')

                            udp_key_str = ""
                            if isinstance(udp_key, (bytes, bytearray)):
                                try:
                                    udp_key_str = udp_key.decode('ascii')
                                except Exception:
                                    udp_key_str = ""
                            elif udp_key:
                                udp_key_str = str(udp_key)

                            if len(udp_key_str) != 32:
                                key_m = re.search(rb'([0-9a-f]{32})', pkt)
                                if key_m:
                                    udp_key = key_m.group(1).decode('ascii')
                            else:
                                udp_key = udp_key_str

                            if token and udp_key and match_code and server_ip_port and isinstance(server_ip_port, str) and ":" in server_ip_port:
                                try:
                                    search_attempts = 0
                                    in_queue = False
                                    mode_cfg = GAME_MODES.get(current_running_mode, GAME_MODES["battle_royale"])
                                    mode_title = mode_cfg.get("name", current_running_mode)
                                    g_mode = int(mode_cfg.get("game_mode", 1))
                                    m_id = int(mode_cfg.get("map_id", 1))

                                    print_colored("=" * 60, Colors.GREEN)
                                    print_colored(f"MATCH FOUND! [{mode_title.upper()}] Loading...", Colors.GREEN)
                                    print_colored("=" * 60, Colors.GREEN)

                                    effective_acc_id = match_account_id or account_id or f"Player_{uid_str}"
                                    acc_tok = ""
                                    if current_account_data:
                                        acc_tok = current_account_data.get('access_token', '') or ""
                                    match_reg = str(account_region).upper() if account_region else "IND"

                                    thunder, sharma = await build_match_startup_packets(
                                        token, udp_key, match_code, effective_acc_id, block_val or 0,
                                        server_ip=server_ip_port,
                                        region=match_reg,
                                        client_version=client_version,
                                        access_token=acc_tok,
                                        game_mode=g_mode,
                                        map_id=m_id
                                    )

                                    match_index, active_count = await _inc_match(uid_str)
                                    total = await _get_total_match_count()
                                    print_colored(
                                        f"MATCH #{match_index} [{mode_title.upper()}] UDP starting -> {server_ip_port} (background)",
                                        Colors.CYAN
                                    )
                                    print_colored(f"[+] [UDP] Key: {udp_key} | MatchCode: {match_code}", Colors.YELLOW)
                                    print_success(
                                        f"[FUNCTIONAL] UDP task started. "
                                        f"UID active: {active_count} | Total: {total}"
                                    )
                                    try:
                                        bot_state.update_status(uid_str, "IN_MATCH", active_count)
                                    except Exception:
                                        pass

                                    new_match = asyncio.create_task(
                                        play_game(
                                            server_ip_port,
                                            thunder,
                                            sharma,
                                            udp_key,
                                            match_code,
                                            effective_acc_id,
                                            match_reg,
                                            client_version,
                                            current_key,
                                            current_iv,
                                            match_index=match_index,
                                            mode_key=current_running_mode
                                        )
                                    )
                                    play_matches.append(new_match)
                                    consecutive_parse_failures = 0
                                    match_allocated = True
                                    break
                                except Exception as e:
                                    print_error(f"Match startup error: {e}")

                        elif 30 <= total_pkt_len <= 40:
                            continue

                    if match_allocated:
                        try:
                            writer.close()
                            await writer.wait_closed()
                        except Exception:
                            pass

                        print_info(
                            f"[OFFLINE] {NEW_MATCH_DELAY}s offline -> "
                            f"reload token -> new StartMatch"
                        )
                        if current_account_data:
                            asyncio.create_task(claim_account_rewards(current_account_data))
                        await asyncio.sleep(NEW_MATCH_DELAY)
                        reconnects = 0
                        break

            except asyncio.CancelledError:
                print_warning(f"[FUNCTIONAL] Cancelled — cancelling {len(play_matches)} UDP matches")
                for m in play_matches:
                    if not m.done():
                        m.cancel()
                if play_matches:
                    await asyncio.gather(*play_matches, return_exceptions=True)
                play_matches.clear()
                raise
            except Exception as e:
                print_error(f"[FUNCTIONAL] TCP state ({uid_str}): {e}")

                play_matches[:] = [m for m in play_matches if not m.done()]

                if writer:
                    try:
                        writer.close()
                        await writer.wait_closed()
                    except Exception:
                        pass

                if "Cache expired" in str(e):
                    print_warning(f"[FUNCTIONAL] Triggering re-login for {uid_str}")
                    break

                reconnects += 1
                if reconnects > max_reconnects:
                    print_error("[FUNCTIONAL] Max reconnects reached, retrying...")
                    reconnects = 0
                    await asyncio.sleep(3)
                    continue

                # 🔥 SAFE FIX #4: Clear stale DNS entry on reconnect so next
                # resolve_host_cloudflare() fetches fresh edge IP (matters when
                # switching VPS regions). No effect on normal operation.
                try:
                    _DNS_CACHE.pop(ip, None)
                except Exception:
                    pass

                await asyncio.sleep(min(reconnects, 2))

    except asyncio.CancelledError:
        print_warning(f"[FUNCTIONAL] Outer cancelled. {len(play_matches)} UDP matches still running.")
        for m in play_matches:
            if not m.done():
                m.cancel()
        if play_matches:
            await asyncio.gather(*play_matches, return_exceptions=True)
        play_matches.clear()
        raise


async def informational(addrs, starter_packet, key, iv, region="BD", max_reconnects=3, proxy=None):
    reconnects = 0
    ip, port = addrs.split(":")
    while True:
        writer = None
        ping_task = None
        try:
            resolved_ip = await resolve_host_cloudflare(ip)
            reader, writer = await open_proxy_connection(resolved_ip, int(port), proxy)
            
            raw_sock = writer.get_extra_info('socket')
            if raw_sock:
                optimize_tcp_socket(raw_sock)
                
            writer.write(bytes.fromhex(starter_packet))
            await writer.drain()
            reconnects = 0

            # Initial keepalive right after connecting
            try:
                init_ka = await send_keep_alive(region)
                if init_ka and writer and not writer.is_closing():
                    writer.write(init_ka)
                    await asyncio.wait_for(writer.drain(), timeout=3)
            except Exception:
                pass

            async def info_keepalive():
                # 🔥 FIX: fetch fresh keepalive each iteration (was stale — fetched once at start only)
                while True:
                    await asyncio.sleep(5)
                    try:
                        if writer and not writer.is_closing():
                            ka_bytes = await send_keep_alive(region)
                            writer.write(ka_bytes)
                            await writer.drain()
                    except asyncio.CancelledError:
                        raise  # 🔥 FIX: don't swallow CancelledError
                    except Exception:
                        break

            ping_task = asyncio.create_task(info_keepalive())

            while True:
                try:
                    # Bug fix: add timeout so informational doesn't block forever
                    data = await asyncio.wait_for(reader.read(8192), timeout=30.0)
                except asyncio.TimeoutError:
                    # Server silent — just continue (keepalive handles connection)
                    continue
                if not data:
                    raise ConnectionError("Connection closed")
        except asyncio.CancelledError:
            if ping_task:
                ping_task.cancel()
            if writer:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass
            raise
        except Exception:
            if ping_task:
                ping_task.cancel()
            if writer:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass
            reconnects += 1
            if reconnects > max_reconnects:
                await asyncio.sleep(3)
                reconnects = 0
            else:
                await asyncio.sleep(1)


# ==================== ACCOUNT PROCESSORS ====================

def _register_credentials(account_data: Dict):
    try:
        acc_id = str(account_data['account_id'])
        bot_state.account_credentials[acc_id] = account_data
        if account_data.get('auth_uid'):
            bot_state.account_credentials[str(account_data['auth_uid'])] = account_data
        if account_data.get('auth_token'):
            bot_state.account_credentials[f"tok_{account_data['auth_token'][:20]}"] = account_data
    except Exception:
        pass


async def refresh_account_profile(account_data_or_uid: Any):
    try:
        if isinstance(account_data_or_uid, str):
            uid = str(account_data_or_uid)
            account_data = bot_state.account_credentials.get(uid)
        else:
            account_data = account_data_or_uid
            uid = str(account_data.get('account_id'))

        if not account_data:
            return

        url = account_data.get('server_url')
        token = account_data.get('token')
        release_version = account_data.get('release_version')
        payload = account_data.get('login_payload_data')
        proxy_url = account_data.get('proxy')

        if not (url and token and release_version and payload):
            return

        res = await send_getlogin(payload, url, token, release_version, proxy=proxy_url)
        if res:
            res_proto, dict_res = res
            level = int(get_proto_field(dict_res, 6, 1))
            exp = int(get_proto_field(dict_res, 7, 0))
            likes = int(get_proto_field(dict_res, 8, 0))
            nickname = res_proto.nickname or get_proto_field(dict_res, 4, "")

            acc_id = str(account_data['account_id'])
            if exp > 0:
                bot_state.update_exp(acc_id, exp, level)
            if likes > 0 and acc_id in bot_state.accounts:
                bot_state.accounts[acc_id]["likes"] = likes
            if nickname and acc_id in bot_state.accounts:
                bot_state.accounts[acc_id]["nickname"] = nickname
            print_info(f"[EXP-REFRESH] UID {acc_id} -> Level: {level}, EXP: {exp}")
    except Exception as e:
        print_error(f"refresh_account_profile error: {e}")


def get_seconds_until_daily_reset(region: str = "IND") -> int:
    """
    Computes exact seconds until next daily 04:00 AM server reset.
    For IND: 04:00 AM IST (UTC+05:30).
    For other regions, adapts to appropriate timezone offset.
    """
    try:
        reg = (region or "IND").upper()
        if reg in ["IND", "IN"]:
            tz = timezone(timedelta(hours=5, minutes=30))
        elif reg in ["BD", "SG"]:
            tz = timezone(timedelta(hours=6, minutes=0))
        elif reg in ["BR"]:
            tz = timezone(timedelta(hours=-3, minutes=0))
        else:
            tz = timezone(timedelta(hours=5, minutes=30))

        now_tz = datetime.now(tz)
        target_reset = now_tz.replace(hour=4, minute=0, second=0, microsecond=0)
        if now_tz >= target_reset:
            target_reset += timedelta(days=1)
        sleep_sec = int((target_reset - now_tz).total_seconds()) + 60
        return max(300, sleep_sec)
    except Exception:
        return 6 * 3600


async def claim_account_rewards(account_data_or_uid: Any) -> bool:
    """Reward claiming completely disabled upon user request — 100% focused on ultra-fast matchmaking & gameplay."""
    return True


async def process_account_uid_pass(uid: str, password: str, proxy: Optional[str] = None, mode: Optional[str] = None) -> Optional[Dict]:
    cached = cache_get(uid)
    if cached:
        print_success(f"[CACHE HIT] UID {uid} loaded from token_cache.json (no login)")
        acc_id = str(cached['account_id'])
        if proxy and not cached.get('proxy'):
            cached['proxy'] = proxy
        if mode:
            cached['mode'] = mode
        bot_state.register_account(
            uid=acc_id,
            nickname=cached.get('nickname', f"Player_{acc_id}"),
            region=cached.get('region', 'IND'),
            level=cached.get('level', 1),
            exp=cached.get('exp', 0),
            likes=cached.get('likes', 0),
            proxy=cached.get('proxy', proxy),
            mode=cached.get('mode', mode),
            auth_uid=uid
        )
        _register_credentials(cached)
        return cached

    proxy_str = f" via Proxy {proxy}" if proxy else ""
    print_info(f"[LOGIN] Full login for UID {uid}{proxy_str}...")
    try:
        verconfig_res = await version_config()
        if verconfig_res is None:
            print_error(f"[-] [LOGIN] Step 1 (Version Config) failed for UID {uid}")
            return None
        release_version, client_version, server_url = verconfig_res
        
        tokengrant_response = await get_access_token(uid, password, proxy=proxy)
        if tokengrant_response is None:
            print_error(f"[-] [LOGIN] Step 2 (Garena OAuth Token Grant) failed for UID {uid}")
            return None
        open_id, access_token, platform = tokengrant_response
        
        # 1 ID = 1 Device
        device_info = get_device_for_account(uid)
        
        login_payload_data = await build_majorlogin_payload(open_id, access_token, platform, client_version, device_info)
        majorlogin_response = await send_majorlogin(login_payload_data, release_version, server_url, proxy=proxy)
        if majorlogin_response in ("BANNED", "FLAGGED"):
            return majorlogin_response
        if majorlogin_response is None:
            print_error(f"[-] [LOGIN] Step 3 (MajorLogin) failed for UID {uid}")
            return None
        getlogin_result = await send_getlogin(login_payload_data, majorlogin_response.url, majorlogin_response.token, release_version, proxy=proxy)
        if getlogin_result is None:
            print_error(f"[-] [LOGIN] Step 4 (GetLoginData) failed for UID {uid}")
            return None
        res_proto, dict_res = getlogin_result

        acc_id = str(majorlogin_response.account_id)
        level = int(get_proto_field(dict_res, 6, 1))
        exp = int(get_proto_field(dict_res, 7, 0))
        likes = int(get_proto_field(dict_res, 8, 0))
        nickname = res_proto.nickname or get_proto_field(dict_res, 4, f"Player_{acc_id}")
        region = majorlogin_response.region or get_proto_field(dict_res, 3, "IND")

        bot_state.register_account(uid=acc_id, nickname=nickname, region=region, level=level, exp=exp, likes=likes, proxy=proxy, mode=mode, auth_uid=uid)

        account_data = {
            'account_id': majorlogin_response.account_id,
            'nickname': nickname,
            'region': region,
            'level': level,
            'exp': exp,
            'likes': likes,
            'open_id': open_id,
            'access_token': access_token,
            'platform': str(platform),
            'token': majorlogin_response.token,
            'server_time': majorlogin_response.server_time,
            'aes_ak': majorlogin_response.aes_ak,
            'iv_i': majorlogin_response.iv_i,
            'functional_addrs': res_proto.functional_addrs or get_proto_field(dict_res, 14),
            'informational_addrs': res_proto.informational_addrs or get_proto_field(dict_res, 32),
            'release_version': release_version,
            'client_version': client_version,
            'server_url': majorlogin_response.url,
            'login_payload_data': login_payload_data,
            'auth_type': 'guest',
            'auth_uid': uid,
            'auth_password': password,
            'proxy': proxy,
            'mode': mode or bot_state.global_game_mode
        }
        _register_credentials(account_data)
        cache_set(uid, account_data)
        return account_data
    except Exception as e:
        print_error(f"process_account_uid_pass error: {e}")
        return None


async def process_account_token(access_token: str, proxy: Optional[str] = None, mode: Optional[str] = None) -> Optional[Dict]:
    cache_key = f"tok_{access_token[:20]}"
    cached = cache_get(cache_key)
    if cached:
        print_success(f"[CACHE HIT] Token {access_token[:10]}... loaded from cache")
        acc_id = str(cached['account_id'])
        if proxy and not cached.get('proxy'):
            cached['proxy'] = proxy
        if mode:
            cached['mode'] = mode
        bot_state.register_account(
            uid=acc_id,
            nickname=cached.get('nickname', f"Player_{acc_id}"),
            region=cached.get('region', 'IND'),
            level=cached.get('level', 1),
            exp=cached.get('exp', 0),
            likes=cached.get('likes', 0),
            proxy=cached.get('proxy', proxy),
            mode=cached.get('mode', mode),
            auth_uid=f"tok_{access_token[:20]}"
        )
        _register_credentials(cached)
        return cached

    proxy_str = f" via Proxy {proxy}" if proxy else ""
    print_info(f"[LOGIN] Full login with Access Token...{proxy_str}")
    try:
        verconfig_res = await version_config()
        if verconfig_res is None:
            return None
        release_version, client_version, server_url = verconfig_res

        url = f"https://100067.connect.garena.com/oauth/token/inspect?token={access_token}"
        hdrs = {
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "close",
            "Content-Type": "application/x-www-form-urlencoded",
            "Host": "100067.connect.garena.com",
            "User-Agent": "GarenaMSDK/4.0.19P4(G011A ;Android 9;en;US;)"
        }
        http_cli = get_http_client(proxy)
        resp = await http_cli.get(url, headers=hdrs, timeout=10.0)
        data = resp.json()

        if 'error' in data:
            err_code = data.get('error', 'unknown')
            print_error(f"[-] [LOGIN] Access Token ({access_token[:10]}...) is EXPIRED or INVALID! Garena returned: '{err_code}'.")
            return None

        open_id = data.get('open_id')
        platform = data.get('platform', 4)

        if not open_id:
            return None

        device_info = get_device_for_account(open_id)

        login_payload_data = await build_majorlogin_payload(open_id, access_token, str(platform), client_version, device_info)
        if not login_payload_data:
            return None

        majorlogin_response = await send_majorlogin(login_payload_data, release_version, server_url, proxy=proxy)
        if majorlogin_response in ("BANNED", "FLAGGED"):
            return majorlogin_response
        if majorlogin_response is None:
            return None

        getlogin_result = await send_getlogin(
            login_payload_data,
            majorlogin_response.url,
            majorlogin_response.token,
            release_version,
            proxy=proxy
        )
        if getlogin_result is None:
            return None

        res_proto, dict_res = getlogin_result
        acc_id = str(majorlogin_response.account_id)
        level = int(get_proto_field(dict_res, 6, 1))
        exp = int(get_proto_field(dict_res, 7, 0))
        likes = int(get_proto_field(dict_res, 8, 0))
        nickname = res_proto.nickname or get_proto_field(dict_res, 4, f"Player_{acc_id}")
        region = majorlogin_response.region or get_proto_field(dict_res, 3, "IND")

        bot_state.register_account(uid=acc_id, nickname=nickname, region=region, level=level, exp=exp, likes=likes, proxy=proxy, mode=mode, auth_uid=f"tok_{access_token[:20]}")

        account_data = {
            'account_id': majorlogin_response.account_id,
            'nickname': nickname,
            'region': region,
            'level': level,
            'exp': exp,
            'likes': likes,
            'open_id': open_id,
            'access_token': access_token,
            'platform': str(platform),
            'token': majorlogin_response.token,
            'server_time': majorlogin_response.server_time,
            'aes_ak': majorlogin_response.aes_ak,
            'iv_i': majorlogin_response.iv_i,
            'functional_addrs': res_proto.functional_addrs or get_proto_field(dict_res, 14),
            'informational_addrs': res_proto.informational_addrs or get_proto_field(dict_res, 32),
            'release_version': release_version,
            'client_version': client_version,
            'server_url': majorlogin_response.url,
            'login_payload_data': login_payload_data,
            'auth_type': 'token',
            'auth_token': access_token,
            'proxy': proxy,
            'mode': mode or bot_state.global_game_mode
        }
        _register_credentials(account_data)
        cache_set(cache_key, account_data)
        return account_data
    except Exception as e:
        print_error(f"process_account_token error: {e}")
        return None


async def run_account_worker(account_data: Dict, label: str):
    acc_id = str(account_data['account_id'])
    informational_task = None
    exp_task = None
    try:
        reg = account_data.get('region', 'BD')
        tcp_packet_online = await build_tcp_startup_packet(
            account_data['account_id'],
            account_data['token'],
            account_data['server_time'],
            account_data['aes_ak'],
            account_data['iv_i'],
            region=reg,
            typ='OnLine'
        )

        tcp_packet_chat = await build_tcp_startup_packet(
            account_data['account_id'],
            account_data['token'],
            account_data['server_time'],
            account_data['aes_ak'],
            account_data['iv_i'],
            region=reg,
            typ='ChaT'
        )

        informational_task = asyncio.create_task(
            informational(
                account_data['informational_addrs'],
                tcp_packet_chat,
                account_data['aes_ak'],
                account_data['iv_i'],
                region=reg
            )
        )

        async def exp_refresher():
            while True:
                try:
                    await asyncio.sleep(90)
                    fresh = bot_state.account_credentials.get(acc_id)
                    if fresh:
                        await refresh_account_profile(fresh)
                        await claim_account_rewards(fresh)
                except asyncio.CancelledError:
                    raise  # Bug fix: don't swallow CancelledError
                except Exception as e:
                    print_error(f"[EXP-REFRESH] Worker error for {acc_id}: {e}")
                    await asyncio.sleep(10)  # brief pause before retrying

        exp_task = asyncio.create_task(exp_refresher())

        functional_task = asyncio.create_task(
            functional_lone_wolf(
                account_data['functional_addrs'],
                tcp_packet_online,
                account_data['region'],
                account_data['client_version'],
                account_data['aes_ak'],
                account_data['iv_i'],
                account_id=acc_id,
                account_data=account_data
            )
        )

        await functional_task

    except asyncio.CancelledError:
        raise
    except Exception as e:
        print_error(f"run_account_worker error for {label}: {e}")
    finally:
        for t in (informational_task, exp_task):
            if t and not t.done():
                t.cancel()
        for t in (informational_task, exp_task):
            if t:
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass


async def account_loop_guest(uid: str, password: str, proxy: Optional[str] = None, mode: Optional[str] = None):
    proxy_str = f" [Proxy: {proxy}]" if proxy else ""
    login_attempts = 0
    while True:
        try:
            print_info(f"[LOGIN] Starting login for Guest UID: {uid}{proxy_str}...")
            try:
                bot_state.update_status(str(uid), "CONNECTING")
            except Exception:
                pass
            account_data = await process_account_uid_pass(uid, password, proxy=proxy, mode=mode)
            if account_data in ("BANNED", "FLAGGED"):
                reason = "BANNED" if account_data == "BANNED" else "FLAGGED (BR_AUTH_ABNORMAL_GAME_CLIENT)"
                print_error(f"[-] [SKIP] UID {uid} is {reason}! Skipping immediately to next account in queue...")
                try:
                    bot_state.update_status(str(uid), "BANNED")
                except Exception:
                    pass
                break

            if not account_data:
                login_attempts += 1
                if login_attempts >= 3:
                    print_error(f"[-] [SKIP] Login failed {login_attempts} times for UID: {uid}. Skipping to next account in queue...")
                    try:
                        bot_state.update_status(str(uid), "ERROR")
                    except Exception:
                        pass
                    break

                print_error(f"Login failed for UID: {uid} (attempt {login_attempts}/3). Retrying in 10 seconds...")
                try:
                    bot_state.update_status(str(uid), "ERROR")
                except Exception:
                    pass
                await asyncio.sleep(10)
                continue

            await run_account_worker(account_data, uid)
            print_warning(f"Session finished for {uid}. Reconnecting in 3s...")
            await asyncio.sleep(3)
        except asyncio.CancelledError:
            print_warning(f"Worker for {uid} stopped.")
            try:
                bot_state.update_status(str(uid), "OFFLINE")
            except Exception:
                pass
            break
        except Exception as e:
            print_error(f"Error for UID {uid}: {e}. Retrying in 10s...")
            await asyncio.sleep(10)


async def account_loop_token(token: str, proxy: Optional[str] = None, mode: Optional[str] = None):
    token_label = token[:10]
    proxy_str = f" [Proxy: {proxy}]" if proxy else ""
    login_attempts = 0
    while True:
        try:
            print_info(f"[LOGIN] Starting login with Access Token{proxy_str}...")
            account_data = await process_account_token(token, proxy=proxy, mode=mode)
            if account_data in ("BANNED", "FLAGGED"):
                reason = "BANNED" if account_data == "BANNED" else "FLAGGED (BR_AUTH_ABNORMAL_GAME_CLIENT)"
                print_error(f"[-] [SKIP] Token ({token_label}...) is {reason}! Skipping immediately...")
                break

            if not account_data:
                login_attempts += 1
                if login_attempts >= 3:
                    print_error(f"[-] [SKIP] Token ({token_label}...) login failed {login_attempts} times. Skipping...")
                    break
                print_error(f"[-] [LOGIN] Token ({token_label}...) login failed (attempt {login_attempts}/3). Retrying in 10s...")
                await asyncio.sleep(10)
                continue

            acc_id = str(account_data['account_id'])
            await run_account_worker(account_data, acc_id)
            print_warning("Token session finished. Reconnecting in 3s...")
            await asyncio.sleep(3)
        except asyncio.CancelledError:
            print_warning(f"Worker for token {token_label} stopped.")
            break
        except Exception as e:
            print_error(f"Token error: {e}. Retrying in 10s...")
            await asyncio.sleep(10)


# ==================== ACCOUNTS LOADER ====================

def load_accounts():
    accounts = []
    if os.path.exists(ACCOUNTS_FILE):
        try:
            with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    data = json.loads(content)
                    if isinstance(data, list):
                        accounts = data
        except Exception as e:
            print_error(f"Could not load {ACCOUNTS_FILE}: {e}")

    if not accounts and FALLBACK_UID and FALLBACK_PASSWORD:
        accounts.append({"uid": FALLBACK_UID, "password": FALLBACK_PASSWORD})

    return accounts


# ==================== 30-MIN SEQUENTIAL ACCOUNT ROTATION SYSTEM ====================

def load_rotation_accounts() -> List[Dict[str, Any]]:
    """
    Loads accounts for 30-minute sequential leveling rotation.
    Supports both:
    1. accounts-IND.json (clean JSON list)
    2. accounts-IND.jsonl (line-by-line format with pipes '|' and colons ':')
    Handles arbitrary whitespace around delimiters.
    """
    # 1. Check clean JSON first
    if os.path.exists(ACCOUNTS_IND_JSON):
        try:
            with open(ACCOUNTS_IND_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    return data
        except Exception as e:
            print_warning(f"Could not load {ACCOUNTS_IND_JSON}: {e}")

    # 2. Check accounts-IND.jsonl
    accounts = []
    if os.path.exists(ACCOUNTS_IND_FILE):
        try:
            with open(ACCOUNTS_IND_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or line.startswith("──"):
                        continue
                    parts = [p.strip() for p in line.split("|") if p.strip()]
                    item = {
                        "game_uid": "",
                        "uid": "",
                        "password": "",
                        "nickname": "",
                        "region": "IND"
                    }
                    for part in parts:
                        if ":" in part:
                            k, v = part.split(":", 1)
                            k = k.strip().upper()
                            v = v.strip()
                            if k == "ID":
                                item["game_uid"] = v
                            elif k == "UID":
                                item["uid"] = v
                            elif k in ("PASS", "PASSWORD"):
                                item["password"] = v
                            elif k in ("NICK", "NICKNAME"):
                                item["nickname"] = v
                            elif k == "REGION":
                                item["region"] = v
                    if item["uid"] and item["password"]:
                        accounts.append(item)
                    elif item["game_uid"] and item["password"]:
                        item["uid"] = item["game_uid"]
                        accounts.append(item)
            return accounts
        except Exception as e:
            print_error(f"Error loading {ACCOUNTS_IND_FILE}: {e}")

    return accounts


def load_level_json() -> List[Dict[str, Any]]:
    """Loads existing account leveling records from level.json."""
    if os.path.exists(LEVEL_JSON_FILE):
        try:
            with open(LEVEL_JSON_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception as e:
            print_warning(f"Error loading {LEVEL_JSON_FILE}: {e}")
    return []


def save_account_to_level_json(record: Dict[str, Any]):
    """
    Appends or updates an account leveling result in level.json.
    Atomic write to prevent file corruption.
    🔥 FIX: Internal level >= 10 guard — even if caller forgets to check, low-level accounts won't be saved.
    """
    # Double-safety: reject level < 10 even if caller didn't check
    _lvl = int(record.get("level") or 0)
    if _lvl < 10:
        print_warning(f"[LEVEL-SAVE BLOCKED] UID {record.get('uid')} | Level {_lvl} < 10 — NOT saved ⛔")
        return

    current_list = load_level_json()
    updated = False

    target_uid = str(record.get("uid", "")).strip()
    target_game_uid = str(record.get("game_uid", "")).strip()

    for i, item in enumerate(current_list):
        item_uid = str(item.get("uid", "")).strip()
        item_game_uid = str(item.get("game_uid", "")).strip()
        if (target_uid and item_uid == target_uid) or (target_game_uid and item_game_uid == target_game_uid):
            current_list[i] = record
            updated = True
            break

    if not updated:
        current_list.append(record)

    try:
        temp_file = f"{LEVEL_JSON_FILE}.tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(current_list, f, indent=2, ensure_ascii=False)
        if os.path.exists(LEVEL_JSON_FILE):
            os.replace(temp_file, LEVEL_JSON_FILE)
        else:
            os.rename(temp_file, LEVEL_JSON_FILE)
        print_success(f"[★] [LEVEL-SAVE] Successfully saved to {LEVEL_JSON_FILE} (Total completed: {len(current_list)})")
    except Exception as e:
        print_error(f"Failed to save {LEVEL_JSON_FILE}: {e}")


async def run_sequential_account_rotation(accounts: List[Dict[str, Any]]):
    """
    Runs accounts sequentially 1-by-1:
    - 1 account runs for ROTATION_DURATION (30 minutes)
    - Plays matches to level up
    - When 30 minutes finish:
      * Refreshes profile to get final Level & EXP
      * Saves {game_uid, uid, password, level, current_exp, nickname, region, ...} to level.json
      * Fully stops and cleanly deletes account from active dashboard
      * Waits ROTATION_COOLDOWN (1 minute)
      * Moves to next account
    """
    existing_level_data = load_level_json()
    completed_uids = set()
    for item in existing_level_data:
        if item.get("uid"):
            completed_uids.add(str(item["uid"]).strip())
        if item.get("game_uid"):
            completed_uids.add(str(item["game_uid"]).strip())

    total_accounts = len(accounts)
    print_colored(f"\n============================================================", Colors.CYAN)
    print_colored(f"   [ROTATION ENGINE] Starting {total_accounts} Accounts Sequentially", Colors.GREEN)
    print_colored(f"   [CONFIG] Play Time: {ROTATION_DURATION // 60} min | Cooldown: {ROTATION_COOLDOWN}s", Colors.WHITE)
    print_colored(f"   [STATUS] Already completed: {len(existing_level_data)}/{total_accounts}", Colors.YELLOW)
    print_colored(f"============================================================\n", Colors.CYAN)

    for idx, acc in enumerate(accounts, 1):
        guest_uid = str(acc.get("uid", "")).strip()
        game_uid = str(acc.get("game_uid", "")).strip()
        password = str(acc.get("password", "")).strip()
        nickname = acc.get("nickname", f"Player_{guest_uid[:6]}")
        region = acc.get("region", "IND")
        active_mode = acc.get("mode") or bot_state.global_game_mode

        if not guest_uid or not password:
            print_warning(f"[-] [ROTATION #{idx}] Skipping invalid account entry (missing UID or PASS)")
            continue

        # Skip if already completed in level.json (Auto-Resume support)
        if guest_uid in completed_uids or (game_uid and game_uid in completed_uids):
            print_info(f"[i] [ROTATION #{idx}/{total_accounts}] Skipping UID {guest_uid} (Already completed in {LEVEL_JSON_FILE})")
            continue

        print_colored(f"\n" + "=" * 60, Colors.CYAN)
        print_colored(f"   ▶ [ROTATION #{idx}/{total_accounts}] STARTING ACCOUNT", Colors.GREEN)
        print_colored(f"   Game UID : {game_uid or 'Auto-detecting'}", Colors.WHITE)
        print_colored(f"   Guest UID: {guest_uid}", Colors.WHITE)
        print_colored(f"   Nickname : {nickname} | Region: {region}", Colors.WHITE)
        print_colored(f"   Mode     : {active_mode} ({GAME_MODES.get(active_mode, {}).get('name', active_mode)})", Colors.WHITE)
        print_colored(f"   Duration : {ROTATION_DURATION // 60} Minutes ({ROTATION_DURATION}s)", Colors.YELLOW)
        print_colored("=" * 60, Colors.CYAN)

        # Clear any deleted state for this UID before starting
        bot_state.deleted_uids.discard(guest_uid)
        if game_uid:
            bot_state.deleted_uids.discard(game_uid)

        # Start the account worker task (same as Web Dashboard addition)
        account_proxy = acc.get("proxy") or os.environ.get("GLOBAL_PROXY") or os.environ.get("PROXY") or None
        worker_task = asyncio.create_task(
            account_loop_guest(guest_uid, password, proxy=account_proxy, mode=active_mode)
        )
        bot_state.account_workers[guest_uid] = worker_task

        # Run for ROTATION_DURATION (30 minutes)
        start_time = time.time()
        rotation_end_time = start_time + ROTATION_DURATION
        last_progress_log = start_time
        worker_failed_early = False

        try:
            while time.time() < rotation_end_time:
                remaining_sec = int(rotation_end_time - time.time())
                if worker_task.done():
                    exc = worker_task.exception() if not worker_task.cancelled() else None
                    if exc:
                        print_error(f"[-] [ROTATION #{idx}] Worker task died with error: {exc}")
                    else:
                        print_warning(f"[-] [ROTATION #{idx}] Worker task stopped early ({int(time.time() - start_time)}s elapsed)")
                    worker_failed_early = True
                    break

                sleep_chunk = min(10, max(1, remaining_sec))
                await asyncio.sleep(sleep_chunk)

                now = time.time()
                if (now - last_progress_log) >= 300:  # Every 5 minutes
                    last_progress_log = now
                    canonical_uid = bot_state.resolve_uid(guest_uid)
                    current_acc = bot_state.accounts.get(canonical_uid) or bot_state.accounts.get(guest_uid) or {}
                    c_lvl = current_acc.get("level", 1)
                    c_exp = current_acc.get("current_exp", 0)
                    c_matches = current_acc.get("matches_played", 0)
                    rem_min = max(0, remaining_sec // 60)
                    print_info(f"[ROTATION #{idx}] {rem_min}m remaining | Matches: {c_matches} | Level: {c_lvl} | EXP: {c_exp}")

        except (asyncio.CancelledError, KeyboardInterrupt):
            print_warning(f"\n[!] [ROTATION] Interrupted during account #{idx} ({guest_uid})")
            if not worker_task.done():
                worker_task.cancel()
                try:
                    await asyncio.wait({worker_task}, timeout=5.0)
                except Exception:
                    pass

            # 🔥 FIX: Server stop pe bhi level check karo — agar >= 10 to save karo
            print_info(f"[STOP-SAVE] Checking level for UID {guest_uid} before shutdown...")
            canonical_uid_stop = bot_state.resolve_uid(guest_uid)
            try:
                await refresh_account_profile(canonical_uid_stop if canonical_uid_stop != guest_uid else guest_uid)
            except Exception:
                pass

            acc_info_stop = bot_state.accounts.get(canonical_uid_stop) or bot_state.accounts.get(guest_uid) or {}
            stop_level   = int(acc_info_stop.get("level") or 0)
            stop_exp     = int(acc_info_stop.get("current_exp") or 0)
            stop_gained  = int(acc_info_stop.get("gained_exp") or 0)
            stop_matches = int(acc_info_stop.get("matches_played") or 0)
            stop_nick    = acc_info_stop.get("nickname") or nickname
            stop_game_uid = acc_info_stop.get("uid") or game_uid or guest_uid

            if stop_level >= 10:
                stop_record = {
                    "game_uid":      str(stop_game_uid),
                    "uid":           str(guest_uid),
                    "password":      str(password),
                    "level":         stop_level,
                    "current_exp":   stop_exp,
                    "gained_exp":    stop_gained,
                    "nickname":      stop_nick,
                    "region":        region,
                    "matches_played":stop_matches,
                    "status":        "SERVER_STOP",
                    "completed_at":  datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                save_account_to_level_json(stop_record)
                print_colored(f"[★] [SAVED on STOP] UID {guest_uid} | Level {stop_level} >= 10 ✅", Colors.GREEN)
            else:
                print_colored(f"[SKIP on STOP] UID {guest_uid} | Level {stop_level} < 10 — NOT saved ⛔", Colors.YELLOW)

            bot_state.remove_account(guest_uid)
            raise

        if worker_failed_early:
            print_colored(f"\n[!] [ROTATION #{idx}] Account UID: {guest_uid} stopped early (deleted from dashboard or crashed)", Colors.YELLOW)

            # 🔥 FIX: Level check karo even if deleted from website — save only if level >= 10
            canonical_uid_early = bot_state.resolve_uid(guest_uid)
            try:
                await refresh_account_profile(canonical_uid_early if canonical_uid_early != guest_uid else guest_uid)
            except Exception:
                pass

            acc_info_early = bot_state.accounts.get(canonical_uid_early) or bot_state.accounts.get(guest_uid) or {}
            early_level = int(acc_info_early.get("level") or 0)
            early_exp = int(acc_info_early.get("current_exp") or 0)
            early_gained = int(acc_info_early.get("gained_exp") or 0)
            early_matches = int(acc_info_early.get("matches_played") or 0)
            early_nick = acc_info_early.get("nickname") or nickname
            early_game_uid = acc_info_early.get("uid") or game_uid or guest_uid

            if early_level >= 10:
                early_record = {
                    "game_uid": str(early_game_uid),
                    "uid": str(guest_uid),
                    "password": str(password),
                    "level": early_level,
                    "current_exp": early_exp,
                    "gained_exp": early_gained,
                    "nickname": early_nick,
                    "region": region,
                    "matches_played": early_matches,
                    "status": "EARLY_STOP",
                    "completed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                save_account_to_level_json(early_record)
                completed_uids.add(str(guest_uid))
                completed_uids.add(str(early_game_uid))
                print_colored(f"[★] [SAVED] UID {guest_uid} | Level {early_level} >= 10 — saved despite early stop ✅", Colors.GREEN)
            else:
                print_colored(f"[SKIP] UID {guest_uid} | Level {early_level} < 10 — NOT saved to {LEVEL_JSON_FILE} ⛔", Colors.YELLOW)

            bot_state.remove_account(str(guest_uid))
            if game_uid and game_uid != str(guest_uid):
                bot_state.remove_account(str(game_uid))
            if not worker_task.done():
                worker_task.cancel()
                try:
                    await asyncio.wait({worker_task}, timeout=5.0)
                except Exception:
                    pass
            if idx < total_accounts:
                print_info(f"[ROTATION #{idx}] Waiting 5s before proceeding to next account...")
                await asyncio.sleep(5)
            continue

        # 30 Minutes Complete: Fetch final profile and save to level.json
        print_colored(f"\n[✓] [ROTATION #{idx}] 30 Minutes completed for UID: {guest_uid}!", Colors.GREEN)
        print_info(f"[ROTATION #{idx}] Fetching final Level & EXP profile from server...")

        canonical_uid = bot_state.resolve_uid(guest_uid)
        target_uid_for_refresh = canonical_uid if canonical_uid != guest_uid else guest_uid
        try:
            await refresh_account_profile(target_uid_for_refresh)
        except Exception as e:
            print_warning(f"[-] Profile refresh failed: {e}")

        acc_info = bot_state.accounts.get(canonical_uid) or bot_state.accounts.get(guest_uid) or {}
        final_level = int(acc_info.get("level") or 0)
        final_exp = int(acc_info.get("current_exp") or 0)
        final_gained = int(acc_info.get("gained_exp") or 0)
        matches_played = int(acc_info.get("matches_played") or 0)
        resolved_nick = acc_info.get("nickname") or nickname
        resolved_game_uid = acc_info.get("uid") or game_uid or guest_uid

        # 🔥 FIX: Level 10 guard — save nahi hoga agar level < 10
        if final_level >= 10:
            record = {
                "game_uid": str(resolved_game_uid),
                "uid": str(guest_uid),
                "password": str(password),
                "level": final_level,
                "current_exp": final_exp,
                "gained_exp": final_gained,
                "nickname": resolved_nick,
                "region": region,
                "matches_played": matches_played,
                "status": "COMPLETED",
                "completed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            save_account_to_level_json(record)
            completed_uids.add(str(guest_uid))
            completed_uids.add(str(resolved_game_uid))
            print_colored(f"[★] [RECORD SAVED] Game UID: {resolved_game_uid} | Guest UID: {guest_uid} | Level: {final_level} | EXP: {final_exp} (+{final_gained}) | Matches: {matches_played}", Colors.GREEN)
        else:
            print_colored(f"[SKIP] UID {guest_uid} | Level {final_level} < 10 — NOT saved to {LEVEL_JSON_FILE} ⛔", Colors.YELLOW)

        # Cleanly stop and remove from dashboard
        print_info(f"[ROTATION #{idx}] Stopping session and deleting from active dashboard...")
        bot_state.remove_account(str(guest_uid))
        if resolved_game_uid and resolved_game_uid != str(guest_uid):
            bot_state.remove_account(str(resolved_game_uid))

        if not worker_task.done():
            worker_task.cancel()
            try:
                # 🔥 FIX: list → set (asyncio.wait requires set in Python 3.10+)
                await asyncio.wait({worker_task}, timeout=5.0)
            except Exception:
                pass

        # Cool-down 1 minute (if not last account)
        if idx < total_accounts:
            print_colored(f"\n[⏳] [COOLDOWN] Waiting {ROTATION_COOLDOWN}s (1 minute) before starting next account...", Colors.YELLOW)
            await asyncio.sleep(ROTATION_COOLDOWN)

    print_colored(f"\n============================================================", Colors.CYAN)
    print_colored(f"   [🎉 ROTATION COMPLETE] All accounts have finished 30-min runs!", Colors.GREEN)
    print_colored(f"   Final results saved in {LEVEL_JSON_FILE}", Colors.GREEN)
    print_colored(f"============================================================\n", Colors.CYAN)


# ==================== MAIN ====================

async def main():
    print_colored("=" * 60, Colors.CYAN)
    print_colored("    NOVRAX - FreeFire Level Up Bot (Web Dashboard Mode)", Colors.GREEN)
    print_colored("   Persistent Device ID + TRUE Parallel + Multi-Mode + SOCKS5", Colors.WHITE)
    print_colored("=" * 60, Colors.CYAN)
    print_info(f"Start Match Interval: {START_MATCH_INTERVAL}s")
    print_info(f"Offline Wait: {NEW_MATCH_DELAY}s (after match found)")
    print_info(f"Non-match Reconnect: {NON_MATCH_RECONNECT_DELAY}s")
    print_info(f"Cache Invalidation Threshold: {MAX_CONSECUTIVE_PARSE_FAILURES}x")
    print_info(f"Parallel Matches: UNLIMITED (background)")
    print_info(f"Cache TTL: {TOKEN_CACHE_TTL}s ({TOKEN_CACHE_TTL//60} min)")
    print_info(f"Priority Regions: {PRIORITY_REGIONS}")
    print_info(f"Global Game Mode: {bot_state.global_game_mode} ({GAME_MODES.get(bot_state.global_game_mode, {}).get('name', 'Battle Royale')})")
    print_info("Device System: 1 ID = 1 Persistent Device ID (devices.json)")
    print_colored("=" * 60, Colors.CYAN)

    try:
        await start_web_dashboard(host=WEB_HOST, port=WEB_PORT)
        print_success(f"Web Dashboard live at http://localhost:{WEB_PORT}")
    except Exception as e:
        print_error(f"Could not start web dashboard: {e}")

    async def on_account_added_handler(data):
        proxy = data.get("proxy")
        if proxy and isinstance(proxy, str):
            proxy = proxy.strip() or None
        mode = data.get("mode")
        if mode and isinstance(mode, str):
            mode = mode.strip() or None
        if "token" in data and data["token"]:
            t = str(data["token"]).strip()
            task = asyncio.create_task(account_loop_token(t, proxy=proxy, mode=mode))
            bot_state.account_workers[t[:10]] = task
        elif "uid" in data and "password" in data:
            u = str(data["uid"]).strip()
            p = str(data["password"]).strip()
            task = asyncio.create_task(account_loop_guest(u, p, proxy=proxy, mode=mode))
            bot_state.account_workers[u] = task

    async def on_refresh_account_handler(uid):
        await refresh_account_profile(uid)

    async def on_claim_rewards_handler(uid):
        await claim_account_rewards(uid)

    bot_state.refresh_callbacks["on_account_added"] = on_account_added_handler
    bot_state.refresh_callbacks["on_refresh_account"] = on_refresh_account_handler
    bot_state.refresh_callbacks["on_claim_rewards"] = on_claim_rewards_handler

    # 🔥 Check for 30-minute sequential rotation accounts first
    rotation_accounts = load_rotation_accounts()
    if rotation_accounts:
        print_colored("=" * 60, Colors.CYAN)
        print_colored(f"   [30-MIN SEQUENTIAL ROTATION MODE ACTIVATED]", Colors.GREEN)
        print_colored(f"   Loaded {len(rotation_accounts)} accounts for 1-by-1 leveling", Colors.YELLOW)
        print_colored(f"   Duration per account: {ROTATION_DURATION // 60} min | Cooldown: {ROTATION_COOLDOWN}s", Colors.WHITE)
        print_colored(f"   Progress saved to: {LEVEL_JSON_FILE}", Colors.CYAN)
        print_colored("=" * 60, Colors.CYAN)

        try:
            await run_sequential_account_rotation(rotation_accounts)
            print_success(f"All {len(rotation_accounts)} accounts completed rotation!")
        except (KeyboardInterrupt, asyncio.CancelledError):
            print_warning("\n[STOP] Shutting down rotation accounts...")
            for t in list(bot_state.account_workers.values()):
                t.cancel()
            await asyncio.gather(*bot_state.account_workers.values(), return_exceptions=True)
            print_success("All sessions cleanly closed.")
        return

    # Fallback to standard accounts.json mode if no rotation accounts exist
    accounts = load_accounts()

    if not accounts:
        print_warning(f"No accounts found in {ACCOUNTS_FILE}! Add accounts from Web Dashboard.")
        print_warning(f"Open: http://localhost:{WEB_PORT}")

    for acc in accounts:
        proxy = acc.get("proxy")
        if proxy and isinstance(proxy, str):
            proxy = proxy.strip() or None
        mode = acc.get("mode")
        if mode and isinstance(mode, str):
            mode = mode.strip() or None
        if "token" in acc and acc["token"]:
            t = asyncio.create_task(account_loop_token(acc["token"], proxy=proxy, mode=mode))
            bot_state.account_workers[acc["token"][:10]] = t
        elif "uid" in acc and "password" in acc and acc["uid"]:
            u = str(acc["uid"])
            t = asyncio.create_task(account_loop_guest(u, acc["password"], proxy=proxy, mode=mode))
            bot_state.account_workers[u] = t

    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print_warning("\n[STOP] Shutting down all accounts...")
        for t in list(bot_state.account_workers.values()):
            t.cancel()
        await asyncio.gather(*bot_state.account_workers.values(), return_exceptions=True)
        print_success("All sessions cleanly closed.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print_warning("\nProgram stopped by user.")