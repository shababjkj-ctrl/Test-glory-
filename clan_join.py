# -*- coding: utf-8 -*-
"""
Clan Join Module — OB55
Auto-joins FreeFire clans using tokens from token_cache.json
"""
import os, json, asyncio
import httpx
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

# ⭐ Case-safe import — dono naming conventions handle
try:
    import ReqCLan_pb2
except ImportError:
    try:
        import reqClan_pb2 as ReqCLan_pb2
    except ImportError:
        ReqCLan_pb2 = None

import encode_id_clan_pb2
import data_pb2
import jwt as pyjwt

RELEASE_VERSION = "OB55"
KEY = bytes([89,103,38,116,99,37,68,69,117,104,54,37,90,99,94,56])
IV  = bytes([54,111,121,90,68,114,50,50,69,51,121,99,104,106,77,37])


def get_region_url(region):
    r = str(region).upper()
    if r == "IND":
        return "https://client.ind.freefiremobile.com"
    if r in ("BR", "US", "SAC", "NA"):
        return "https://client.us.freefiremobile.com/"
    return "https://clientbp.ggblueshark.com/"


def _encrypt(pb_bytes):
    return AES.new(KEY, AES.MODE_CBC, IV).encrypt(pad(pb_bytes, AES.block_size))


def _headers(token, base_url):
    host = base_url.replace("https://", "").replace("http://", "").rstrip("/")
    return {
        "Expect": "100-continue",
        "Authorization": f"Bearer {token}",
        "X-Unity-Version": "2018.4.11f1",
        "X-GA": "v1 1",
        "ReleaseVersion": RELEASE_VERSION,
        "Content-Type": "application/octet-stream",
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 11; SM-A305F)",
        "Host": host,
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip"
    }


def get_region_from_jwt(token):
    try:
        d = pyjwt.decode(token, options={"verify_signature": False})
        return str(d.get('lock_region', 'IND')).upper()
    except Exception:
        return 'IND'


async def join_clan_single(token, clan_id, region="IND", retries=2):
    if ReqCLan_pb2 is None:
        return {"success": False, "error": "ReqCLan_pb2 module not found"}

    base_url = get_region_url(region)
    msg = ReqCLan_pb2.MyMessage()
    msg.field_1 = int(clan_id)
    encrypted = _encrypt(msg.SerializeToString())
    url = f"{base_url}/RequestJoinClan"

    last_err = None
    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
                r = await client.post(url, headers=_headers(token, base_url), content=encrypted)
                if r.status_code == 200:
                    return {"success": True, "status_code": 200, "attempt": attempt + 1}
                last_err = f"HTTP {r.status_code}: {r.text[:100]}"
        except Exception as e:
            last_err = str(e)
        if attempt < retries:
            await asyncio.sleep(1.0 + attempt * 0.5)
    return {"success": False, "error": last_err}


async def fetch_clan_info(token, clan_id, region="IND"):
    base_url = get_region_url(region)
    my_data = encode_id_clan_pb2.MyData()
    my_data.field1 = int(clan_id)
    my_data.field2 = 1
    encrypted = _encrypt(my_data.SerializeToString())
    url = f"{base_url}/GetClanInfoByClanID"
    try:
        async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
            r = await client.post(url, headers=_headers(token, base_url), content=encrypted)
            if r.status_code == 200:
                resp = data_pb2.response()
                resp.ParseFromString(r.content)
                return {
                    "clan_name": getattr(resp, "special_code", "Unknown"),
                    "clan_level": getattr(resp, "level", 0),
                    "clan_xp": int(getattr(resp, "total_playtime", 0))
                }
    except Exception:
        pass
    return {"clan_name": "Unknown", "clan_level": 0, "clan_xp": 0}


def load_tokens_from_cache(region=None, uids=None):
    if not os.path.exists("token_cache.json"):
        return []
    try:
        with open("token_cache.json", "r", encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        return []

    out, seen = [], set()
    target_uids = {str(u) for u in uids} if uids else None
    target_region = str(region).upper() if region else None

    for key, cred in cache.items():
        if not isinstance(cred, dict):
            continue
        token = cred.get("token")
        if not token or not isinstance(token, str):
            continue
        acc_id = str(cred.get("account_id", ""))
        if not acc_id or acc_id in seen:
            continue
        acc_region = str(cred.get("region", "IND")).upper()
        if target_region and acc_region != target_region:
            continue
        if target_uids and acc_id not in target_uids:
            continue
        seen.add(acc_id)
        out.append({
            "account_id": acc_id,
            "token": token,
            "region": acc_region,
            "nickname": cred.get("nickname", f"Player_{acc_id[:6]}")
        })
    return out


async def join_clan_bulk(clan_id, region, uids=None, max_concurrent=4):
    accounts = load_tokens_from_cache(region=region, uids=uids)
    if not accounts:
        return {
            "success": 0, "failed": 0, "total": 0, "results": [],
            "error": f"No tokens found for region {region}"
        }

    sem = asyncio.Semaphore(max_concurrent)
    results = []

    async def worker(acc):
        async with sem:
            r = await join_clan_single(acc["token"], clan_id, acc["region"])
            results.append({"account_id": acc["account_id"], "nickname": acc["nickname"], **r})
            return r

    await asyncio.gather(*[worker(a) for a in accounts], return_exceptions=True)
    success_count = sum(1 for r in results if r.get("success"))
    return {
        "clan_id": clan_id, "region": region,
        "total": len(results), "success": success_count,
        "failed": len(results) - success_count,
        "results": results
    }