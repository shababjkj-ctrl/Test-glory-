# -*- coding: utf-8 -*-
"""
FreeFire Level Up Bot - Web Dashboard + Auth + Admin + Coupons + Glory Launch
"""

import asyncio
import json
import os
import time
import hashlib
import secrets
from typing import Dict, List, Any, Optional
from aiohttp import web
import urllib3
import requests
import httpx
import jwt
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import ReqCLan_pb2
import encode_id_clan_pb2
import data_pb2
import output_pb2
from google.protobuf.json_format import MessageToDict

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ═══════════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════════
ELITE_ARENA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Temples")
TEMPLATE_PATH = os.path.join(ELITE_ARENA_DIR, "index.html")

OB = "OB55"
KEY = bytes([89,103,38,116,99,37,68,69,117,104,54,37,90,99,94,56])
IV  = bytes([54,111,121,90,68,114,50,50,69,51,121,99,104,106,77,37])

GAME_HEADERS = {
    "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9)",
    "Connection": "Keep-Alive",
    "Accept-Encoding": "gzip",
    "Content-Type": "application/octet-stream",
    "X-Unity-Version": "2018.4.11f1",
    "X-GA": "v1 1",
    "ReleaseVersion": OB,
    "Expect": "100-continue"
}

REGION_SERVER_MAP = {
    "IND": ("https://client.ind.freefiremobile.com", "client.ind.freefiremobile.com"),
    "ME":  ("https://clientbp.ggblueshark.com", "clientbp.ggblueshark.com"),
    "VN":  ("https://clientbp.ggpolarbear.com", "clientbp.ggpolarbear.com"),
    "BD":  ("https://clientbp.ggwhitehawk.com", "clientbp.ggwhitehawk.com"),
    "PK":  ("https://clientbp.ggblueshark.com", "clientbp.ggblueshark.com"),
    "SG":  ("https://clientbp.ggpolarbear.com", "clientbp.ggpolarbear.com"),
    "BR":  ("https://client.us.freefiremobile.com", "client.us.freefiremobile.com"),
    "NA":  ("https://client.us.freefiremobile.com", "client.us.freefiremobile.com"),
    "ID":  ("https://clientbp.ggpolarbear.com", "clientbp.ggpolarbear.com"),
    "RU":  ("https://clientbp.ggpolarbear.com", "clientbp.ggpolarbear.com"),
    "TH":  ("https://clientbp.ggpolarbear.com", "clientbp.ggpolarbear.com"),
    "SAC": ("https://client.br.freefiremobile.com", "client.br.freefiremobile.com"),
    "TW":  ("https://client.tw.freefiremobile.com", "client.tw.freefiremobile.com"),
    "CIS": ("https://client.cis.freefiremobile.com", "client.cis.freefiremobile.com"),
}
DEFAULT_SERVER_URL = "https://clientbp.ggblueshark.com"
DEFAULT_HOST = "clientbp.ggblueshark.com"


def encrypt_payload(data):
    return AES.new(KEY, AES.MODE_CBC, IV).encrypt(pad(data, AES.block_size))


def get_server_info(region):
    val = REGION_SERVER_MAP.get(str(region).upper(), DEFAULT_SERVER_URL)
    return val if isinstance(val, tuple) else (val, DEFAULT_HOST)


def get_server_url(region):
    return get_server_info(region)[0]


def fetch_single_clan(clan_id, region, token_cache):
    server_base, host = get_server_info(region)
    url = f"{server_base}/GetClanInfoByClanID"
    try:
        my_data = encode_id_clan_pb2.MyData()
        my_data.field1 = int(clan_id)
        my_data.field2 = 1
        payload = encrypt_payload(my_data.SerializeToString())
    except Exception as e:
        return {"clan_id": clan_id, "error": f"Protobuf failed: {e}"}

    response = None
    for uid, creds in token_cache.items():
        token = creds.get('token')
        if not token:
            continue
        headers = GAME_HEADERS.copy()
        headers["Authorization"] = f"Bearer {token}" if not token.startswith("Bearer ") else token
        headers["Host"] = host
        try:
            res = requests.post(url, headers=headers, data=payload, verify=False, timeout=15.0)
            if res.status_code == 200:
                response = res; break
            elif "expired" in res.text.lower() or res.status_code == 401:
                continue
            else:
                response = res; break
        except Exception:
            continue

    if not response or response.status_code != 200:
        return {"clan_id": clan_id, "error": "All tokens failed or expired"}

    full_response = {}
    resp = None
    try:
        resp = data_pb2.response()
        resp.ParseFromString(response.content)
        full_response = MessageToDict(resp, preserving_proto_field_name=True)
    except Exception:
        pass

    guild_xp = 0
    if resp:
        for field_desc, val in resp.ListFields():
            if field_desc.number == 36 and isinstance(val, int):
                guild_xp = val; break
    if guild_xp == 0 and full_response:
        guild_xp = int(full_response.get("field_36") or full_response.get("xp") or 0)

    return {
        "captain_id": getattr(resp, "captain_id", 0) if resp else full_response.get("captain_id", 0),
        "clan_id": int(clan_id),
        "clan_level": getattr(resp, "rank", 4) if resp else full_response.get("rank", 4),
        "clan_name": getattr(resp, "special_code", None) if resp else (full_response.get("special_code") or f"Guild_{clan_id}"),
        "current_officer": full_response.get("current_officer", 0),
        "current_members": full_response.get("current_members", 1),
        "max_members": full_response.get("max_members", 50),
        "Total guild xp": int(guild_xp),
        "welcome_message": getattr(resp, "welcome_message", "") if resp else full_response.get("welcome_message", ""),
        "region": region, "xp": int(guild_xp),
        "raw_response_bytes": response.content.hex()
    }


async def request_clan_async(jwt_token, clan_id, region):
    server_url = get_server_url(region)
    msg = ReqCLan_pb2.MyMessage()
    msg.field_1 = int(clan_id)
    payload = encrypt_payload(msg.SerializeToString())
    headers = GAME_HEADERS.copy()
    headers["Authorization"] = f"Bearer {jwt_token}" if not jwt_token.startswith("Bearer ") else jwt_token
    url = f"{server_url}/RequestJoinClan"
    async with httpx.AsyncClient(verify=False, timeout=8.0) as client:
        r = await client.post(url, headers=headers, content=payload)
        return r.status_code, r.text


EXP_TABLE: Dict[int, int] = {
    1: 0, 2: 48, 3: 202, 4: 544, 5: 1012, 6: 1844, 7: 2792, 8: 3800,
    9: 4870, 10: 6004, 11: 7192, 12: 8448, 13: 9760, 14: 11140, 15: 12566,
    16: 14060, 17: 15610, 18: 17224, 19: 18902, 20: 20632, 21: 22424, 22: 24278,
    23: 26192, 24: 28166, 25: 30200, 26: 32294, 27: 34448, 28: 37804, 29: 41274,
    30: 44870, 31: 48582, 32: 53394, 33: 58566, 34: 64096, 35: 69994, 36: 76460,
    37: 83506, 38: 91128, 39: 99322, 40: 108092, 41: 120144, 42: 133266, 43: 147472,
    44: 162760, 45: 179126, 46: 196572, 47: 215368, 48: 235516, 49: 257010, 50: 279860,
    51: 304056, 52: 348318, 53: 394982, 54: 444044, 55: 495508, 56: 549364, 57: 633756,
    58: 721744, 59: 813336, 60: 908522, 61: 1041438, 62: 1180352, 63: 1325266,
    64: 1476184, 65: 1634300, 66: 1840946, 67: 2056594, 68: 2281242, 69: 2514880,
    70: 2757530, 71: 3059506, 72: 3372284, 73: 3699456, 74: 4041030, 75: 4397002,
    76: 4829104, 77: 5282204, 78: 5756304, 79: 6251408, 80: 6776502, 81: 7381324,
    82: 8043154, 83: 8752982, 84: 9510808, 85: 10316338, 86: 11277190, 87: 12291748,
    88: 13360304, 89: 14482858, 90: 15659418, 91: 17026708, 92: 18453950, 93: 19941280,
    94: 21488570, 95: 23095858, 96: 24763138, 97: 26490428, 98: 28378704, 99: 30124996,
    100: 32032884
}


# ═══════════════════════════════════════════════════════════════════
#  USERS + SESSIONS
# ═══════════════════════════════════════════════════════════════════
USERS_FILE = "users.json"
_sessions: Dict[str, Dict[str, Any]] = {}
SESSION_TTL = 7 * 86400


def _load_users() -> Dict[str, Dict[str, Any]]:
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, 'r', encoding='utf-8') as f:
                d = json.load(f)
                if isinstance(d, dict):
                    return d
        except Exception:
            pass
    return {}


def _save_users(u):
    try:
        tmp = USERS_FILE + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(u, f, indent=2)
        os.replace(tmp, USERS_FILE)
    except Exception:
        pass


def _hash_password(pw, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac('sha256', pw.encode(), salt.encode(), 100_000)
    return f"{salt}${h.hex()}"


def _verify_password(pw, stored):
    try:
        salt = stored.split('$', 1)[0]
        return _hash_password(pw, salt) == stored
    except Exception:
        return False


def _create_session(username, role='user'):
    token = secrets.token_urlsafe(32)
    _sessions[token] = {'username': username, 'role': role, 'created_at': time.time()}
    return token


def _get_session(request):
    token = request.cookies.get('session')
    if not token or token not in _sessions:
        return None
    sess = _sessions[token]
    if time.time() - sess['created_at'] > SESSION_TTL:
        _sessions.pop(token, None); return None
    return sess


def _normalize_username(u):
    return str(u).strip().lower().replace(' ', '_')


def _display_username(u):
    return str(u).replace('_', ' ').strip()


def _seed_admin():
    users = _load_users()
    if 'dg_drift' not in users:
        users['dg_drift'] = {
            'username': 'dg_drift', 'display_name': 'Eʟɪᴛᴇ Aʀᴇɴᴀ',
            'password_hash': _hash_password('Eʟɪᴛᴇ Aʀᴇɴᴀ'), 'role': 'admin',
            'basic_credits': 1000, 'premium_credits': 100,
            'created_at': time.time(), 'seeded': True
        }
        _save_users(users)
        print("[SEED] Admin account created")
    elif users['dg_drift'].get('role') != 'admin':
        users['dg_drift']['role'] = 'admin'
        _save_users(users)


# ═══════════════════════════════════════════════════════════════════
#  COUPONS
# ═══════════════════════════════════════════════════════════════════
COUPONS_FILE = "coupons.json"


def _load_coupons():
    if os.path.exists(COUPONS_FILE):
        try:
            with open(COUPONS_FILE, 'r', encoding='utf-8') as f:
                d = json.load(f)
                if isinstance(d, dict):
                    return d
        except Exception:
            pass
    return {}


def _save_coupons(c):
    try:
        tmp = COUPONS_FILE + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(c, f, indent=2)
        os.replace(tmp, COUPONS_FILE)
    except Exception:
        pass


def _generate_coupon_code():
    a = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return '-'.join(''.join(secrets.choice(a) for _ in range(4)) for _ in range(3))


# ═══════════════════════════════════════════════════════════════════
#  AUTH HANDLERS
# ═══════════════════════════════════════════════════════════════════
async def handle_auth_signup(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    username = _normalize_username(data.get('username', ''))
    password = str(data.get('password', ''))

    if len(username) < 3:
        return web.json_response({"error": "Username too short"}, status=400)
    if len(username) > 20:
        return web.json_response({"error": "Username too long"}, status=400)
    if not username.replace('_', '').isalnum():
        return web.json_response({"error": "Username must be alphanumeric"}, status=400)
    if len(password) < 6:
        return web.json_response({"error": "Password too short"}, status=400)

    users = _load_users()
    if username in users:
        return web.json_response({"error": "Username already exists"}, status=400)

    users[username] = {
        'username': username, 'display_name': _display_username(username),
        'password_hash': _hash_password(password), 'role': 'user',
        'basic_credits': 0, 'premium_credits': 0, 'created_at': time.time()
    }
    _save_users(users)
    return web.json_response({"success": True, "message": "Account created"})


async def handle_auth_login(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    username = _normalize_username(data.get('username', ''))
    password = str(data.get('password', ''))

    users = _load_users()
    user = users.get(username)
    if not user or not _verify_password(password, user.get('password_hash', '')):
        return web.json_response({"error": "Invalid credentials"}, status=401)

    token = _create_session(username, user.get('role', 'user'))
    response = web.json_response({
        "success": True, "username": username,
        "display_name": user.get('display_name', _display_username(username)),
        "role": user.get('role', 'user')
    })
    response.set_cookie('session', token, httponly=True, max_age=SESSION_TTL, path='/', samesite='Lax')
    return response


async def handle_auth_logout(request):
    token = request.cookies.get('session')
    if token and token in _sessions:
        _sessions.pop(token, None)
    response = web.json_response({"success": True})
    response.del_cookie('session', path='/')
    return response


async def handle_auth_me(request):
    sess = _get_session(request)
    if not sess:
        return web.json_response({"error": "Not authenticated"}, status=401)
    users = _load_users()
    user = users.get(sess['username'], {})
    return web.json_response({
        "username": sess['username'],
        "display_name": user.get('display_name', _display_username(sess['username'])),
        "role": sess.get('role', 'user'),
        "basic_credits": user.get('basic_credits', 0),
        "premium_credits": user.get('premium_credits', 0),
        "max_groups": 10
    })


async def handle_change_password(request):
    sess = _get_session(request)
    if not sess:
        return web.json_response({"error": "Not authenticated"}, status=401)
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    cur = str(data.get('current_password', ''))
    new = str(data.get('new_password', ''))
    if len(new) < 6:
        return web.json_response({"error": "Password too short"}, status=400)

    users = _load_users()
    user = users.get(sess['username'])
    if not user or not _verify_password(cur, user.get('password_hash', '')):
        return web.json_response({"error": "Current password incorrect"}, status=401)

    user['password_hash'] = _hash_password(new)
    _save_users(users)
    return web.json_response({"success": True, "message": "Password changed"})


# ═══════════════════════════════════════════════════════════════════
#  COUPON HANDLERS
# ═══════════════════════════════════════════════════════════════════
async def handle_coupon_create(request):
    sess = _get_session(request)
    if not sess:
        return web.json_response({"error": "Not authenticated"}, status=401)
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    basic = int(data.get('basic_credits', 0) or 0)
    premium = int(data.get('premium_credits', 0) or 0)
    if basic < 0 or premium < 0:
        return web.json_response({"error": "Credits cannot be negative"}, status=400)
    if basic == 0 and premium == 0:
        return web.json_response({"error": "Select at least 1 credit"}, status=400)

    users = _load_users()
    user = users.get(sess['username'])
    if not user:
        return web.json_response({"error": "User not found"}, status=404)

    if basic > user.get('basic_credits', 0):
        return web.json_response({"error": f"Only {user.get('basic_credits', 0)} basic credits"}, status=400)
    if premium > user.get('premium_credits', 0):
        return web.json_response({"error": f"Only {user.get('premium_credits', 0)} premium credits"}, status=400)

    user['basic_credits'] -= basic
    user['premium_credits'] -= premium
    _save_users(users)

    coupons = _load_coupons()
    code = _generate_coupon_code()
    while code in coupons:
        code = _generate_coupon_code()

    coupons[code] = {
        'code': code, 'created_by': sess['username'],
        'basic_credits': basic, 'premium_credits': premium,
        'status': 'active', 'created_at': time.time(),
        'used_by': None, 'used_at': None
    }
    _save_coupons(coupons)
    return web.json_response({
        "success": True,
        "coupon": {"code": code, "basic_credits": basic, "premium_credits": premium}
    })


async def handle_coupon_mine(request):
    sess = _get_session(request)
    if not sess:
        return web.json_response([])
    coupons = _load_coupons()
    mine = [{
        'code': c['code'], 'basic_credits': c.get('basic_credits', 0),
        'premium_credits': c.get('premium_credits', 0), 'status': c.get('status', 'active'),
        'created_at': c.get('created_at'), 'used_by': c.get('used_by'), 'used_at': c.get('used_at')
    } for c in coupons.values() if c.get('created_by') == sess['username']]
    mine.sort(key=lambda x: x.get('created_at') or 0, reverse=True)
    return web.json_response(mine)


async def handle_coupon_redeem(request):
    sess = _get_session(request)
    if not sess:
        return web.json_response({"error": "Not authenticated"}, status=401)
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    code = str(data.get('code', '')).strip().upper()
    if not code:
        return web.json_response({"error": "Code required"}, status=400)

    coupons = _load_coupons()
    coupon = coupons.get(code)
    if not coupon:
        return web.json_response({"error": "Invalid coupon"}, status=404)
    if coupon.get('status') != 'active':
        return web.json_response({"error": f"Already {coupon.get('status')}"}, status=400)
    if coupon.get('created_by') == sess['username']:
        return web.json_response({"error": "Cannot redeem your own coupon"}, status=400)

    users = _load_users()
    user = users.get(sess['username'])
    if not user:
        return web.json_response({"error": "User not found"}, status=404)

    basic = coupon.get('basic_credits', 0)
    premium = coupon.get('premium_credits', 0)
    user['basic_credits'] = user.get('basic_credits', 0) + basic
    user['premium_credits'] = user.get('premium_credits', 0) + premium
    _save_users(users)

    coupon['status'] = 'used'
    coupon['used_by'] = sess['username']
    coupon['used_at'] = time.time()
    _save_coupons(coupons)

    return web.json_response({
        "success": True, "basic_credits": basic, "premium_credits": premium,
        "new_basic": user['basic_credits'], "new_premium": user['premium_credits']
    })


async def handle_coupon_redeemed(request):
    sess = _get_session(request)
    if not sess:
        return web.json_response([])
    coupons = _load_coupons()
    r = [{
        'code': c['code'], 'basic_credits': c.get('basic_credits', 0),
        'premium_credits': c.get('premium_credits', 0),
        'created_by': c.get('created_by'), 'used_at': c.get('used_at')
    } for c in coupons.values() if c.get('used_by') == sess['username']]
    r.sort(key=lambda x: x.get('used_at') or 0, reverse=True)
    return web.json_response(r)


async def handle_coupon_cancel(request):
    sess = _get_session(request)
    if not sess:
        return web.json_response({"error": "Not authenticated"}, status=401)
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    code = str(data.get('code', '')).strip().upper()
    coupons = _load_coupons()
    coupon = coupons.get(code)
    if not coupon:
        return web.json_response({"error": "Not found"}, status=404)
    if coupon.get('created_by') != sess['username']:
        return web.json_response({"error": "Not your coupon"}, status=403)
    if coupon.get('status') != 'active':
        return web.json_response({"error": f"Cannot cancel — {coupon.get('status')}"}, status=400)

    users = _load_users()
    user = users.get(sess['username'])
    if user:
        user['basic_credits'] = user.get('basic_credits', 0) + coupon.get('basic_credits', 0)
        user['premium_credits'] = user.get('premium_credits', 0) + coupon.get('premium_credits', 0)
        _save_users(users)

    coupon['status'] = 'cancelled'
    _save_coupons(coupons)
    return web.json_response({
        "success": True, "message": "Cancelled & refunded",
        "new_basic": user['basic_credits'] if user else 0,
        "new_premium": user['premium_credits'] if user else 0
    })


# ═══════════════════════════════════════════════════════════════════
#  ADMIN HANDLERS
# ═══════════════════════════════════════════════════════════════════
def _require_admin(request):
    sess = _get_session(request)
    if not sess:
        return web.json_response({"error": "Not authenticated"}, status=401)
    if sess.get('role') != 'admin':
        return web.json_response({"error": "Admin access required"}, status=403)
    return None


async def handle_admin_page(request):
    sess = _get_session(request)
    if not sess or sess.get('role') != 'admin':
        raise web.HTTPFound('/login?msg=Admin+access+required')
    return await serve_elite_arena_file("admin.html")


async def handle_admin_overview(request):
    err = _require_admin(request)
    if err: return err
    users = _load_users()
    coupons = _load_coupons()
    bot_accounts = 0
    bot_online = 0
    try:
        bot_accounts = len(bot_state.accounts)
        bot_online = sum(1 for a in bot_state.accounts.values() if a.get('status') in ('ONLINE', 'IN_MATCH'))
    except Exception:
        pass
    return web.json_response({
        "total_users": len(users),
        "total_admins": sum(1 for u in users.values() if u.get('role') == 'admin'),
        "total_basic_credits": sum(u.get('basic_credits', 0) for u in users.values()),
        "total_premium_credits": sum(u.get('premium_credits', 0) for u in users.values()),
        "active_coupons": sum(1 for c in coupons.values() if c.get('status') == 'active'),
        "used_coupons": sum(1 for c in coupons.values() if c.get('status') == 'used'),
        "bot_accounts": bot_accounts,
        "bot_online": bot_online,
        "pending_clans": len(getattr(bot_state, 'pending_clans', {})),
        "uptime": int(time.time() - bot_state.start_time)
    })


async def handle_admin_users(request):
    err = _require_admin(request)
    if err: return err
    users = _load_users()
    r = []
    for u_name, u in users.items():
        acc = bot_state.accounts.get(u_name, {})
        r.append({
            "username": u_name,
            "display_name": u.get('display_name', _display_username(u_name)),
            "role": u.get('role', 'user'),
            "basic_credits": u.get('basic_credits', 0),
            "premium_credits": u.get('premium_credits', 0),
            "created_at": u.get('created_at', 0),
            "seeded": u.get('seeded', False),
            "bot_uid": acc.get('uid'),
            "bot_nickname": acc.get('nickname'),
            "bot_status": acc.get('status', 'OFFLINE'),
            "bot_level": acc.get('level', 0),
        })
    r.sort(key=lambda x: x.get('created_at') or 0, reverse=True)
    return web.json_response(r)


async def handle_admin_user_credits(request):
    err = _require_admin(request)
    if err: return err
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    target = _normalize_username(data.get('username', ''))
    basic = int(data.get('basic_credits', 0) or 0)
    premium = int(data.get('premium_credits', 0) or 0)
    mode = str(data.get('mode', 'add')).strip()

    users = _load_users()
    if target not in users:
        return web.json_response({"error": f"User '{target}' not found"}, status=404)

    if mode == 'set':
        users[target]['basic_credits'] = max(0, basic)
        users[target]['premium_credits'] = max(0, premium)
    else:
        users[target]['basic_credits'] = max(0, users[target].get('basic_credits', 0) + basic)
        users[target]['premium_credits'] = max(0, users[target].get('premium_credits', 0) + premium)
    _save_users(users)
    return web.json_response({
        "success": True, "username": target,
        "basic_credits": users[target]['basic_credits'],
        "premium_credits": users[target]['premium_credits']
    })


async def handle_admin_user_role(request):
    err = _require_admin(request)
    if err: return err
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    target = _normalize_username(data.get('username', ''))
    role = str(data.get('role', 'user')).strip().lower()
    if role not in ('user', 'admin'):
        return web.json_response({"error": "Role must be user/admin"}, status=400)

    sess = _get_session(request)
    if target == sess['username']:
        return web.json_response({"error": "Cannot change own role"}, status=400)

    users = _load_users()
    if target not in users:
        return web.json_response({"error": "User not found"}, status=404)
    users[target]['role'] = role
    _save_users(users)
    return web.json_response({"success": True, "username": target, "role": role})


async def handle_admin_user_delete(request):
    err = _require_admin(request)
    if err: return err
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    target = _normalize_username(data.get('username', ''))
    sess = _get_session(request)
    if target == sess['username']:
        return web.json_response({"error": "Cannot delete yourself"}, status=400)

    users = _load_users()
    if target not in users:
        return web.json_response({"error": "User not found"}, status=404)
    del users[target]
    _save_users(users)
    return web.json_response({"success": True, "deleted": target})


async def handle_admin_user_create(request):
    err = _require_admin(request)
    if err: return err
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    username = _normalize_username(data.get('username', ''))
    password = str(data.get('password', ''))
    role = str(data.get('role', 'user')).strip().lower()
    basic = int(data.get('basic_credits', 0) or 0)
    premium = int(data.get('premium_credits', 0) or 0)

    if len(username) < 3:
        return web.json_response({"error": "Username too short"}, status=400)
    if len(password) < 6:
        return web.json_response({"error": "Password too short"}, status=400)
    if role not in ('user', 'admin'):
        return web.json_response({"error": "Invalid role"}, status=400)

    users = _load_users()
    if username in users:
        return web.json_response({"error": "Username exists"}, status=400)

    users[username] = {
        'username': username, 'display_name': _display_username(username),
        'password_hash': _hash_password(password), 'role': role,
        'basic_credits': max(0, basic), 'premium_credits': max(0, premium),
        'created_at': time.time()
    }
    _save_users(users)
    return web.json_response({
        "success": True, "username": username,
        "display_name": users[username]['display_name']
    })


async def handle_admin_all_coupons(request):
    err = _require_admin(request)
    if err: return err
    coupons = _load_coupons()
    r = [{
        "code": c['code'], "created_by": c.get('created_by'),
        "basic_credits": c.get('basic_credits', 0),
        "premium_credits": c.get('premium_credits', 0),
        "status": c.get('status', 'active'),
        "created_at": c.get('created_at'),
        "used_by": c.get('used_by'), "used_at": c.get('used_at')
    } for c in coupons.values()]
    r.sort(key=lambda x: x.get('created_at') or 0, reverse=True)
    return web.json_response(r)


async def handle_admin_coupon_create(request):
    err = _require_admin(request)
    if err: return err
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    basic = int(data.get('basic_credits', 0) or 0)
    premium = int(data.get('premium_credits', 0) or 0)
    target = _normalize_username(data.get('for_user', ''))

    if basic < 0 or premium < 0:
        return web.json_response({"error": "Cannot be negative"}, status=400)
    if basic == 0 and premium == 0:
        return web.json_response({"error": "Specify at least 1 credit"}, status=400)

    sess = _get_session(request)
    users = _load_users()
    creator = target if target else sess['username']

    if creator not in users:
        return web.json_response({"error": f"User '{creator}' not found"}, status=404)

    user = users[creator]
    if basic > user.get('basic_credits', 0):
        return web.json_response({"error": f"{creator} has {user.get('basic_credits', 0)} basic only"}, status=400)
    if premium > user.get('premium_credits', 0):
        return web.json_response({"error": f"{creator} has {user.get('premium_credits', 0)} premium only"}, status=400)

    user['basic_credits'] -= basic
    user['premium_credits'] -= premium
    _save_users(users)

    coupons = _load_coupons()
    code = _generate_coupon_code()
    while code in coupons:
        code = _generate_coupon_code()

    coupons[code] = {
        'code': code, 'created_by': creator,
        'basic_credits': basic, 'premium_credits': premium,
        'status': 'active', 'created_at': time.time(),
        'used_by': None, 'used_at': None
    }
    _save_coupons(coupons)
    return web.json_response({
        "success": True,
        "coupon": {"code": code, "basic_credits": basic, "premium_credits": premium}
    })


async def handle_admin_coupon_revoke(request):
    err = _require_admin(request)
    if err: return err
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    code = str(data.get('code', '')).strip().upper()
    coupons = _load_coupons()
    coupon = coupons.get(code)
    if not coupon:
        return web.json_response({"error": "Not found"}, status=404)
    if coupon.get('status') != 'active':
        return web.json_response({"error": f"Already {coupon.get('status')}"}, status=400)

    creator = coupon.get('created_by')
    users = _load_users()
    if creator and creator in users:
        users[creator]['basic_credits'] = users[creator].get('basic_credits', 0) + coupon.get('basic_credits', 0)
        users[creator]['premium_credits'] = users[creator].get('premium_credits', 0) + coupon.get('premium_credits', 0)
        _save_users(users)

    coupon['status'] = 'cancelled'
    _save_coupons(coupons)
    return web.json_response({"success": True, "message": "Revoked & refunded"})


async def handle_admin_bot_accounts(request):
    err = _require_admin(request)
    if err: return err
    r = []
    try:
        for uid, acc in bot_state.accounts.items():
            r.append({
                "uid": acc.get('uid', uid), "nickname": acc.get('nickname', ''),
                "region": acc.get('region', ''), "level": acc.get('level', 0),
                "exp": acc.get('current_exp', 0), "gained_exp": acc.get('gained_exp', 0),
                "status": acc.get('status', 'OFFLINE'),
                "matches_played": acc.get('matches_played', 0),
                "active_matches": acc.get('active_matches', 0),
                "is_paused": acc.get('is_paused', False),
                "last_updated": acc.get('last_updated', '')
            })
    except Exception:
        pass
    r.sort(key=lambda x: x.get('gained_exp', 0), reverse=True)
    return web.json_response(r)


# ═══════════════════════════════════════════════════════════════════
#  GLORY LAUNCH HANDLERS ⭐
# ═══════════════════════════════════════════════════════════════════
async def handle_client_launch(request):
    sess = _get_session(request)
    if not sess:
        return web.json_response({"error": "Not authenticated"}, status=401)
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    clan_id = str(data.get('clan_id', '')).strip()
    region = str(data.get('region', 'IND')).strip().upper()

    if not clan_id or not clan_id.isdigit():
        return web.json_response({"error": "clan_id must be numeric"}, status=400)

    valid = ("IND", "BD", "ME", "BR", "US", "SAC", "NA",
             "SG", "TH", "VN", "ID", "PK", "CIS", "RU", "TW")
    if region not in valid:
        return web.json_response({"error": f"Invalid region: {region}"}, status=400)

    users = _load_users()
    user = users.get(sess['username'])
    if not user:
        return web.json_response({"error": "User not found"}, status=404)

    credit_type = 'premium' if region in ('ME', 'BR', 'US', 'NA', 'SAC') else 'basic'
    available = user.get(f'{credit_type}_credits', 0)
    if available < 1:
        return web.json_response({
            "error": f"Insufficient {credit_type} credits (1 required)",
            "required": 1, "available": available,
            "credit_type": credit_type, "region": region
        }, status=400)

    user[f'{credit_type}_credits'] -= 1
    _save_users(users)

    bot_state.pending_clans[region] = {
        "clan_id": clan_id,
        "region": region,
        "launched_by": sess['username'],
        "launched_at": time.time(),
        "joined": False
    }
    bot_state.log(f"🏰 Group launched: clan {clan_id} region {region} by {sess['username']}", "success")

    asyncio.create_task(_async_join_group(clan_id, region, sess['username']))

    return web.json_response({
        "success": True, "clan_id": clan_id, "region": region,
        "credit_type": credit_type,
        "remaining_credits": user[f'{credit_type}_credits'],
        "message": f"Group launched! Bots joining clan {clan_id}..."
    })


async def _async_join_group(clan_id, region, launched_by):
    try:
        from clan_join import join_clan_bulk
        res = await join_clan_bulk(clan_id, region)
        joined = res.get('success', 0)
        total = res.get('total', 0)
        if joined > 0:
            entry = bot_state.pending_clans.get(region)
            if entry:
                entry['joined'] = True
                entry['joined_at'] = time.time()
            bot_state.log(f"✅ {joined}/{total} bots joined clan {clan_id} ({region})", "success")
        else:
            bot_state.log(f"❌ Clan join failed: {res.get('error', 'no accounts')}", "warning")
    except Exception as e:
        bot_state.log(f"❌ Clan join error: {e}", "error")


async def handle_admin_join_clan(request):
    err = _require_admin(request)
    if err: return err
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    clan_id = str(data.get('clan_id', '')).strip()
    region = str(data.get('region', 'IND')).strip().upper()
    uids = data.get('uids')

    if not clan_id:
        return web.json_response({"error": "clan_id required"}, status=400)

    try:
        from clan_join import join_clan_bulk
        return web.json_response(await join_clan_bulk(clan_id, region, uids=uids))
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


# ═══════════════════════════════════════════════════════════════════
#  STUB APIs
# ═══════════════════════════════════════════════════════════════════
async def handle_pricing(request):
    return web.json_response({
        "basic_credit_usd": 1.70, "premium_credit_usd": 20.00,
        "regions": [
            {"id": "ind", "region_name": "India", "tier": "basic", "enabled": True},
            {"id": "bd", "region_name": "Bangladesh", "tier": "basic", "enabled": True},
            {"id": "me", "region_name": "Middle East", "tier": "premium", "enabled": True},
            {"id": "br", "region_name": "Brazil", "tier": "premium", "enabled": True},
        ]
    })


async def handle_empty_list(request):
    return web.json_response([])


async def handle_null(request):
    return web.json_response(None)


async def handle_vapid_placeholder(request):
    return web.json_response({"publicKey": ""})


# ═══════════════════════════════════════════════════════════════════
#  STATIC SERVING
# ═══════════════════════════════════════════════════════════════════
async def serve_elite_arena_file(filename):
    fp = os.path.join(ELITE_ARENA_DIR, filename)
    if not os.path.isfile(fp):
        return web.Response(status=404, text=f"ELITE_ARENA/{filename} not found")
    return web.FileResponse(fp)


async def handle_ffglory(request): return await serve_elite_arena_file("ffglory.html")
async def handle_login_page(request): return await serve_elite_arena_file("login.html")
async def handle_signup_page(request): return await serve_elite_arena_file("login.html")
async def handle_client_page(request): return await serve_elite_arena_file("client.html")
async def handle_bot_page(request): return await serve_elite_arena_file("index.html")


async def serve_static(request):
    filename = request.match_info.get('filename', '').lstrip('/')
    if not filename or '..' in filename:
        return web.Response(status=404, text="Not found")
    elite_arena_abs = os.path.abspath(ELITE_ARENA_DIR)
    fp = os.path.abspath(os.path.join(elite_arena_abs, filename))
    if not fp.startswith(elite_arena_abs + os.sep) and fp != elite_arena_abs:
        return web.Response(status=404, text="Not found")
    if not os.path.isfile(fp):
        return web.Response(status=404, text="Not found")
    return web.FileResponse(fp)


# ═══════════════════════════════════════════════════════════════════
#  BOT STATE
# ═══════════════════════════════════════════════════════════════════
def calculate_level_progress(level, current_exp):
    level = max(1, level)
    next_level = min(100, level + 1)
    base = EXP_TABLE.get(level, 0)
    target = EXP_TABLE.get(next_level, base + 50000)
    needed = max(1, target - base)
    earned = max(0, current_exp - base)
    remaining = max(0, target - current_exp)
    pct = min(100.0, max(0.0, (earned / needed) * 100.0))
    return {"next_level": next_level, "base_exp": base, "target_exp": target,
            "needed_for_level": needed, "earned_in_level": earned,
            "remaining_exp": remaining, "progress_pct": round(pct, 1)}


class BotState:
    def __init__(self):
        self.accounts = {}
        self.logs = []
        self.max_logs = 200
        self.total_matches = 0
        self.total_matches_started = 0
        self.total_gained_exp = 0
        self.start_time = time.time()
        self.account_workers = {}
        self.account_token_map = {}
        self.auth_to_game_id = {}
        self.game_to_auth_id = {}
        self.paused_accounts = set()
        self.refresh_callbacks = {}
        self.account_credentials = {}
        self.active_writers = {}
        self.pending_clans: Dict[str, Dict[str, Any]] = {}  # ⭐ NEW

    def log(self, message, level="info", uid=None):
        entry = {"time": time.strftime("%H:%M:%S"), "level": level,
                 "message": message, "uid": str(uid) if uid else None}
        self.logs.append(entry)
        if len(self.logs) > self.max_logs:
            self.logs.pop(0)

    def register_account(self, uid, nickname, region, level, exp, likes=0, token=None, auth_uid=None):
        uid_str = str(uid)
        prog = calculate_level_progress(level or 1, exp)
        lvl_val = level or 1
        mode = "BR" if lvl_val < 3 else "LONE_WOLF"
        if uid_str not in self.accounts:
            self.accounts[uid_str] = {
                "uid": uid_str, "auth_uid": str(auth_uid) if auth_uid else "",
                "nickname": nickname or f"Player_{uid_str[:6]}",
                "region": region or "BD", "level": lvl_val,
                "next_level": prog["next_level"], "mode": mode,
                "mode_label": "Battle Royale" if lvl_val < 3 else "Lone Wolf",
                "initial_exp": exp, "current_exp": exp, "gained_exp": 0,
                "remaining_exp": prog["remaining_exp"],
                "target_exp": prog["target_exp"],
                "needed_for_level": prog["needed_for_level"],
                "earned_in_level": prog["earned_in_level"],
                "progress_pct": prog["progress_pct"],
                "likes": likes or 0,
                "status": "PAUSED" if self.is_paused(uid_str) else "ONLINE",
                "matches_played": 0, "active_matches": 0, "last_match_time": None,
                "token": token or "", "start_time": time.time(),
                "is_paused": self.is_paused(uid_str), "paused_at": None,
                "total_pause_duration": 0.0,
                "last_updated": time.strftime("%H:%M:%S")
            }
        else:
            acc = self.accounts[uid_str]
            if nickname: acc["nickname"] = nickname
            if region: acc["region"] = region
            if level: acc["level"] = level
            if token: acc["token"] = token
            acc["current_exp"] = exp
            acc["gained_exp"] = max(0, exp - acc["initial_exp"])
            acc["progress_pct"] = prog["progress_pct"]
            acc["last_updated"] = time.strftime("%H:%M:%S")
        self.recalc_totals()

    def get_account_uptime(self, uid_str):
        acc = self.accounts.get(uid_str)
        if not acc: return 0
        start_t = acc.get("start_time", time.time())
        total_pause = acc.get("total_pause_duration", 0.0)
        if acc.get("is_paused") and acc.get("paused_at"):
            return max(0, int(acc["paused_at"] - start_t - total_pause))
        return max(0, int(time.time() - start_t - total_pause))

    def is_paused(self, uid):
        return str(uid) in self.paused_accounts

    def toggle_pause(self, uid):
        uid_str = str(uid)
        is_now_paused = not self.is_paused(uid_str)
        if is_now_paused:
            self.paused_accounts.add(uid_str)
            if uid_str in self.accounts:
                self.accounts[uid_str]["is_paused"] = True
                self.accounts[uid_str]["paused_at"] = time.time()
                self.accounts[uid_str]["status"] = "PAUSED"
        else:
            self.paused_accounts.discard(uid_str)
            if uid_str in self.accounts:
                self.accounts[uid_str]["is_paused"] = False
                self.accounts[uid_str]["paused_at"] = None
                self.accounts[uid_str]["status"] = "ONLINE"
        return is_now_paused

    def toggle_pause_all(self):
        any_active = any(not self.is_paused(k) for k in self.accounts.keys())
        for k in list(self.accounts.keys()):
            current_paused = self.is_paused(k)
            if any_active and not current_paused:
                self.toggle_pause(k)
            elif not any_active and current_paused:
                self.toggle_pause(k)
        return any_active

    def update_exp(self, uid, current_exp, level=None):
        uid_str = str(uid)
        if uid_str in self.accounts:
            acc = self.accounts[uid_str]
            old_exp = acc["current_exp"]
            acc["current_exp"] = current_exp
            if level is not None and level > 0:
                acc["level"] = level
            acc["gained_exp"] = max(0, current_exp - acc["initial_exp"])
            prog = calculate_level_progress(acc["level"], current_exp)
            acc["progress_pct"] = prog["progress_pct"]
            acc["last_updated"] = time.strftime("%H:%M:%S")
            diff = current_exp - old_exp
            if diff > 0:
                self.log(f"★ UID {uid_str} gained +{diff:,} EXP", "success", uid_str)
            self.recalc_totals()

    def update_status(self, uid, status, active_matches=None):
        uid_str = str(uid)
        if uid_str in self.accounts:
            self.accounts[uid_str]["status"] = status
            if active_matches is not None:
                self.accounts[uid_str]["active_matches"] = active_matches
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")

    def increment_match(self, uid):
        uid_str = str(uid)
        self.total_matches += 1
        if uid_str in self.accounts:
            self.accounts[uid_str]["matches_played"] += 1
            self.accounts[uid_str]["last_match_time"] = time.strftime("%H:%M:%S")

    def recalc_totals(self):
        self.total_gained_exp = sum(acc.get("gained_exp", 0) for acc in self.accounts.values())


bot_state = BotState()


# ═══════════════════════════════════════════════════════════════════
#  BOT APIs
# ═══════════════════════════════════════════════════════════════════
async def handle_get_stats(request):
    accounts_data = list(bot_state.accounts.values())
    accounts_data.sort(key=lambda x: x.get("gained_exp", 0), reverse=True)
    uptime_sec = max(1, int(time.time() - bot_state.start_time))
    total_gained = bot_state.total_gained_exp
    exp_per_hour = int((total_gained / uptime_sec) * 3600)
    total_active = sum(acc.get("active_matches", 0) for acc in accounts_data)

    for acc in accounts_data:
        uid_k = str(acc.get("uid", ""))
        acc["uptime_seconds"] = bot_state.get_account_uptime(uid_k)
        acc["is_paused"] = bot_state.is_paused(uid_k)

    return web.json_response({
        "total_accounts": len(bot_state.accounts),
        "total_matches": bot_state.total_matches,
        "total_matches_started": bot_state.total_matches_started,
        "total_active_matches": total_active,
        "total_gained_exp": total_gained,
        "exp_per_hour": exp_per_hour,
        "accounts": accounts_data,
        "logs": bot_state.logs[-80:],
        "uptime": uptime_sec,
        "pending_clans": list(bot_state.pending_clans.keys())
    })


async def handle_api_clan_join(request):
    try:
        data = await request.json()
        clan_id = data.get('clan_id')
        if not clan_id:
            return web.json_response({'error': 'clan_id required'}, status=400)
        try:
            with open("token_cache.json", "r", encoding="utf-8") as f:
                token_cache = json.load(f)
        except Exception as e:
            return web.json_response({'error': f'Cache load failed: {e}'}, status=500)
        success = 0; total = 0
        for uid, creds in token_cache.items():
            jwt_token = creds.get('token')
            region = creds.get('region', 'IND')
            if not jwt_token: continue
            total += 1
            try:
                sc, _ = await request_clan_async(jwt_token, clan_id, region)
                if sc == 200: success += 1
            except Exception:
                pass
        return web.json_response({'message': f'Sent for {success}/{total} accounts'}, status=200)
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)


GUILD_CACHE_FILE = "guild_exp_cache.json"


def load_guild_cache():
    if os.path.exists(GUILD_CACHE_FILE):
        try:
            with open(GUILD_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_guild_cache(c):
    try:
        with open(GUILD_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(c, f, indent=4)
    except Exception:
        pass


def get_persisted_baseline_xp(clan_id, current_xp):
    cache = load_guild_cache()
    key = str(clan_id)
    if key not in cache or "old_xp" not in cache[key]:
        cache[key] = {"old_xp": current_xp, "live_xp": current_xp, "gained_exp": 0}
        save_guild_cache(cache)
        return current_xp
    return int(cache[key]["old_xp"])


async def handle_api_guild_info(request):
    try:
        clan_id = request.query.get('guild_id') or request.query.get('clan_id')
        region = (request.query.get('region') or 'IND').upper()
        api_key = request.query.get('key')
        if not api_key or api_key != "XEROX_MODS":
            return web.json_response({"error": "Unauthorized"}, status=401)
        if not clan_id:
            return web.json_response({"error": "guild_id required"}, status=400)
        try:
            with open("token_cache.json", "r", encoding="utf-8") as f:
                token_cache = json.load(f)
        except Exception:
            return web.json_response({"error": "Cache load failed"}, status=503)
        if not token_cache:
            return web.json_response({"error": "Empty cache"}, status=503)
        clan_data = fetch_single_clan(clan_id, region, token_cache)
        if "error" in clan_data:
            return web.json_response(clan_data, status=500)
        current_xp = int(clan_data.get("Total guild xp") or clan_data.get("xp") or 0)
        baseline = get_persisted_baseline_xp(clan_id, current_xp)
        gained = current_xp - baseline
        cache = load_guild_cache()
        cache[str(clan_id)] = {"old_xp": baseline, "live_xp": current_xp, "gained_exp": gained}
        save_guild_cache(cache)
        clan_data["old_xp"] = baseline
        clan_data["gained_exp"] = gained
        return web.json_response({
            "status": "success", "requested_region": region, "queried_clan_id": clan_id,
            "api_response": {
                "DEVLOVER": "XEROX_MODS",
                "TIME AND DATE": time.strftime("%I:%M %p, %A, %B %d, %Y"),
                "clan_basic_info": clan_data
            }
        }, status=200)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_add_account(request):
    try:
        data = await request.json()
        accounts_file = "accounts.json"
        existing = []
        if os.path.exists(accounts_file):
            try:
                with open(accounts_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = []
        if "uid" in data and "password" in data:
            uid = str(data["uid"]).strip()
            pwd = str(data["password"]).strip()
            if not uid or not pwd:
                return web.json_response({"status": "error", "error": "UID+Password required"})
            if uid in bot_state.account_workers:
                try: bot_state.account_workers[uid].cancel()
                except Exception: pass
                bot_state.account_workers.pop(uid, None)
            existing = [a for a in existing if str(a.get("uid", "")) != uid]
            existing.append({"uid": uid, "password": pwd})
            identifier = uid
        elif "token" in data:
            token = str(data["token"]).strip()
            if not token:
                return web.json_response({"status": "error", "error": "Token required"})
            existing = [a for a in existing if a.get("token", "") != token]
            existing.append({"token": token})
            identifier = f"Token_{token[:8]}..."
        else:
            return web.json_response({"status": "error", "error": "Invalid payload"})
        with open(accounts_file, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)
        bot_state.log(f"New account: {identifier}", "success")
        if "on_account_added" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_account_added"](data))
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_delete_account(request):
    try:
        data = await request.json()
        req_uid = str(data.get("uid", "")).strip()
        if not req_uid:
            return web.json_response({"status": "error", "error": "UID required"})
        accounts_file = "accounts.json"
        if os.path.exists(accounts_file):
            with open(accounts_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
            existing = [a for a in existing if str(a.get("uid", "")) != req_uid]
            with open(accounts_file, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2)
        bot_state.accounts.pop(req_uid, None)
        bot_state.account_credentials.pop(req_uid, None)
        if req_uid in bot_state.account_workers:
            try: bot_state.account_workers[req_uid].cancel()
            except Exception: pass
            bot_state.account_workers.pop(req_uid, None)
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_refresh_account(request):
    try:
        data = await request.json()
        uid = str(data.get("uid", "")).strip()
        if "on_refresh_account" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_refresh_account"](uid))
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_restart_account(request):
    try:
        data = await request.json()
        uid = str(data.get("uid", "")).strip()
        if "on_restart_account" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_restart_account"](uid))
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_clear_logs(request):
    bot_state.logs.clear()
    return web.json_response({"status": "ok"})


async def handle_toggle_pause(request):
    try:
        data = await request.json()
        uid = str(data.get("uid", "")).strip()
        if not uid:
            return web.json_response({"status": "error", "error": "UID required"})
        return web.json_response({"status": "ok", "is_paused": bot_state.toggle_pause(uid)})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_toggle_pause_all(request):
    try:
        return web.json_response({"status": "ok", "all_paused": bot_state.toggle_pause_all()})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_api_logs(request):
    logs = []
    for e in bot_state.logs[-80:]:
        if isinstance(e, dict):
            t = e.get("time", ""); msg = e.get("message", ""); lv = e.get("level", "info")
            color = "#34d399" if lv == "success" else ("#f87171" if lv in ("warning", "error") else "#38bdf8")
            logs.append(f'<span style="color:{color}">[{t}] {msg}</span>')
        else:
            logs.append(str(e))
    return web.json_response({"logs": logs}, status=200)


# ═══════════════════════════════════════════════════════════════════
#  START
# ═══════════════════════════════════════════════════════════════════
async def start_web_dashboard(host="0.0.0.0", port=5000):
    _seed_admin()
    app = web.Application()

    # HTML pages
    # Serve the user-provided dashboard HTML directly; no login/signup page required.
    app.router.add_get("/",    handle_bot_page)
    app.router.add_get("/bot", handle_bot_page)
    app.router.add_get("/login",  handle_login_page)
    app.router.add_get("/signup", handle_signup_page)
    app.router.add_get("/client", handle_client_page)
    app.router.add_get("/admin",  handle_admin_page)

    # Auth
    app.router.add_post("/api/auth/signup",          handle_auth_signup)
    app.router.add_post("/api/auth/login",           handle_auth_login)
    app.router.add_post("/api/auth/logout",          handle_auth_logout)
    app.router.add_post("/api/auth/change-password", handle_change_password)
    app.router.add_get ("/api/me",                   handle_auth_me)
    app.router.add_get ("/api/logout",               handle_auth_logout)

    # Coupons
    app.router.add_post("/api/coupons/create",   handle_coupon_create)
    app.router.add_get ("/api/coupons/mine",     handle_coupon_mine)
    app.router.add_post("/api/coupons/redeem",   handle_coupon_redeem)
    app.router.add_get ("/api/coupons/redeemed", handle_coupon_redeemed)
    app.router.add_post("/api/coupons/cancel",   handle_coupon_cancel)

    # Admin
    app.router.add_get ("/api/admin/overview",      handle_admin_overview)
    app.router.add_get ("/api/admin/users",         handle_admin_users)
    app.router.add_post("/api/admin/user/credits",  handle_admin_user_credits)
    app.router.add_post("/api/admin/user/role",     handle_admin_user_role)
    app.router.add_post("/api/admin/user/delete",   handle_admin_user_delete)
    app.router.add_post("/api/admin/user/create",   handle_admin_user_create)
    app.router.add_get ("/api/admin/coupons",       handle_admin_all_coupons)
    app.router.add_post("/api/admin/coupon/create", handle_admin_coupon_create)
    app.router.add_post("/api/admin/coupon/revoke", handle_admin_coupon_revoke)
    app.router.add_get ("/api/admin/bot-accounts",  handle_admin_bot_accounts)
    app.router.add_post("/api/admin/join-clan",     handle_admin_join_clan)

    # ⭐ Glory Launch
    app.router.add_post("/api/client/launch", handle_client_launch)

    # Stubs
    app.router.add_get("/api/pricing",             handle_pricing)
    app.router.add_get("/api/transactions",        handle_empty_list)
    app.router.add_get("/api/client/groups",       handle_empty_list)
    app.router.add_get("/api/client/activity-log", handle_empty_list)
    app.router.add_get("/api/inbox/messages",      handle_empty_list)
    app.router.add_get("/api/notifications",       handle_empty_list)
    app.router.add_get("/api/client/active-alert", handle_null)
    app.router.add_get("/api/vapid-public-key",    handle_vapid_placeholder)

    # Bot APIs
    app.router.add_post("/api/clanjoin",          handle_api_clan_join)
    app.router.add_get ("/api/guildinfo",         handle_api_guild_info)
    app.router.add_get ("/api/stats",             handle_get_stats)
    app.router.add_get ("/api/logs",              handle_api_logs)
    app.router.add_post("/api/account/add",       handle_add_account)
    app.router.add_post("/api/account/delete",    handle_delete_account)
    app.router.add_post("/api/account/refresh",   handle_refresh_account)
    app.router.add_post("/api/account/restart",   handle_restart_account)
    app.router.add_post("/api/account/pause",     handle_toggle_pause)
    app.router.add_post("/api/account/pause_all", handle_toggle_pause_all)
    app.router.add_post("/api/logs/clear",        handle_clear_logs)

    # Catch-all static (LAST)
    app.router.add_get('/{filename:.*}', serve_static)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    return runner