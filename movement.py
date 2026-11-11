# -*- coding: utf-8 -*-
"""
movement.py — Self-contained movement loop + homer auto-skill.

Drop next to app.py. Import from app.py:

    from movement import movement_loop, GameState

Wire-up in play_game() where movement_ctrl.start() would be:

    gs = GameState(my_pid=int(account_id) if str(account_id).isdigit() else 0)
    gs.set_render_pos((128749, 15456, 590657))
    gs.has_server_pos = True
    movement_stop = asyncio.Event()
    movement_task = asyncio.create_task(movement_loop(
        sock, (resolved_ip, port), udp_key_bytes, match_code,
        gs, movement_stop, f"squad_{account_id}", f"uid={account_id}"))

On cleanup (finally block):

    movement_stop.set()
    try: await movement_task
    except: pass

Payload swap: edit MOVEMENT_BODY_OVERRIDE_HEX / MOVEMENT_FULL_OVERRIDE_HEX below.
"""
import asyncio
import math
import random
import struct
import time

# ════════════════════════════════════════════════════════════════════
#  CONSTANTS
# ════════════════════════════════════════════════════════════════════
MOVE_INTERVAL        = 0.15
SKILL_RANGE_MIN      = 800
SKILL_RANGE_MAX      = 1500
CMD_MY_STATE         = 2001
CMD_USE_ACTIVE_SKILL = 248

# ════════════════════════════════════════════════════════════════════
#  PAYLOAD OVERRIDE — DENI edits these two lines
# ════════════════════════════════════════════════════════════════════
#   "" = original _build_position_body path (default)
#   hex = override
#     MOVEMENT_BODY_OVERRIDE_HEX → replaces plaintext body
#                                  (build_packet still TEA+header wraps it)
#     MOVEMENT_FULL_OVERRIDE_HEX → replaces entire final packet
#                                  (build_packet bypassed; you own all bytes)
MOVEMENT_BODY_OVERRIDE_HEX = ""
MOVEMENT_FULL_OVERRIDE_HEX = ""

# ════════════════════════════════════════════════════════════════════
#  LAZY APP IMPORTS
# ════════════════════════════════════════════════════════════════════
_app_cache: dict = {}

def _app():
    if not _app_cache:
        import app as _a
        _app_cache["build_packet"]      = _a.build_packet
        _app_cache["layouts_from_mask"] = _a.layouts_from_mask
    return _app_cache["build_packet"], _app_cache["layouts_from_mask"]

def _log(msg, level="info"):
    try:
        import app as _a
        if   level == "success": _a.print_success(msg)
        elif level == "warning": _a.print_warning(msg)
        elif level == "error":   _a.print_error(msg)
        else:                    _a.print_info(msg)
    except Exception:
        print(f"[{level}] {msg}")

def squad_ok(squad_n, msg): _log(f"[{squad_n}] {msg}", "success")
def dbg(tag, msg):          _log(f"[{tag}] {msg}", "info")
def _udp_log(msg):          _log(msg, "warning")

# ════════════════════════════════════════════════════════════════════
#  HOMER — auto skill cast
# ════════════════════════════════════════════════════════════════════
class Homer:
    def __init__(self, skill_id=1015, cooldown=8.0, warmup=3.0):
        self.skill_id   = skill_id
        self.cooldown   = cooldown
        self.warmup     = warmup
        self.last_cast  = 0.0
        self.fire_count = 0
        self.aim_dx     = 0.0
        self.aim_dy     = 0.0
        self.aim_dz     = 0.0

    def should_cast(self, now, joined_at):
        if now - joined_at < self.warmup:
            return False
        return (now - self.last_cast) >= self.cooldown

    def set_aim_direction(self, dx, dy, dz):
        self.aim_dx = float(dx)
        self.aim_dy = float(dy)
        self.aim_dz = float(dz)

    def mark_cast(self, now, skill_id=None):
        self.last_cast = now
        if skill_id is not None:
            self.skill_id = skill_id
        self.fire_count += 1

    def build_packet_body(self, pid, tick, target_id=0):
        body = bytearray()
        body.extend(struct.pack("<I", int(pid)             & 0xFFFFFFFF))
        body.extend(struct.pack("<I", int(self.skill_id)   & 0xFFFFFFFF))
        body.extend(struct.pack("<I", int(tick)            & 0xFFFFFFFF))
        body.extend(struct.pack("<I", int(target_id)       & 0xFFFFFFFF))
        body.extend(struct.pack("<h", int(self.aim_dx * 100) & 0xFFFF))
        body.extend(struct.pack("<h", int(self.aim_dy * 100) & 0xFFFF))
        body.extend(struct.pack("<h", int(self.aim_dz * 100) & 0xFFFF))
        return bytes(body)

# ════════════════════════════════════════════════════════════════════
#  GAME STATE
# ════════════════════════════════════════════════════════════════════
class GameState:
    def __init__(self, my_pid=0, target_fid=0, joined_at=None):
        self.my_pos         = (0.0, 0.0, 0.0)
        self.target_pos     = None
        self.has_server_pos = False
        self.target_fid     = target_fid
        self.joined_at      = joined_at if joined_at is not None else time.time()
        self._pid           = my_pid
        self._server_time_offset_ms = 0
        self.homer          = Homer()

    def get_render_pos(self):
        return self.my_pos

    def set_render_pos(self, pos):
        self.my_pos = (float(pos[0]), float(pos[1]), float(pos[2]))

    def effective_pid(self):
        return self._pid

    def server_time(self, now):
        elapsed_ms = int((now - self.joined_at) * 1000)
        return (elapsed_ms + self._server_time_offset_ms) & 0xFFFFFFFF

    def advance_pos(self, ddx, ddz):
        self.my_pos = (self.my_pos[0] + ddx, self.my_pos[1] + ddz, self.my_pos[2])

# ════════════════════════════════════════════════════════════════════
#  MOVEMENT PLANNER
# ════════════════════════════════════════════════════════════════════
class MovementPlanner:
    def __init__(self, radius=800.0, speed=60.0, pattern="circle"):
        self.angle     = random.uniform(0, 2 * math.pi)
        self.radius    = radius
        self.speed     = speed
        self.pattern   = pattern
        self.last_step = 0.0
        self.yaw       = 0.0

    def plan(self, state, now):
        dt = now - self.last_step
        if dt <= 0 or dt > 2.0:
            dt = MOVE_INTERVAL
        self.last_step = now

        if self.pattern == "circle":
            self.angle += (2 * math.pi / 8.0) * dt
            if self.angle > 2 * math.pi:
                self.angle -= 2 * math.pi
            tx = self.radius * math.cos(self.angle)
            ty = self.radius * math.sin(self.angle)
        else:
            tx = random.uniform(-self.radius, self.radius)
            ty = random.uniform(-self.radius, self.radius)

        cur = state.get_render_pos() or (0.0, 0.0, 0.0)
        ddx = (tx - cur[0]) * 0.2
        ddz = (ty - cur[1]) * 0.2
        new_pos = (cur[0] + ddx, cur[1] + ddz, cur[2])
        dist = math.sqrt(ddx * ddx + ddz * ddz)
        self.yaw = math.atan2(ddz, ddx)
        return new_pos, ddx, ddz, dist

    def next_yaw(self):
        return int((self.yaw + math.pi) / (2 * math.pi) * 65535) & 0xFFFF

# ════════════════════════════════════════════════════════════════════
#  BODY BUILDER — default dynamic
# ════════════════════════════════════════════════════════════════════
def _build_position_body(pid, render, yaw, st, ddx, ddz, jump, slide):
    x_i = int(render[0]) & 0xFFFFFFFF
    y_i = int(render[1]) & 0xFFFFFFFF
    z_i = int(render[2]) & 0xFFFFFFFF
    body = bytearray()
    body.extend(struct.pack("<I", pid & 0xFFFFFFFF))
    body.extend(struct.pack("<I", x_i))
    body.extend(struct.pack("<I", y_i))
    body.extend(struct.pack("<I", z_i))
    body.extend(struct.pack("<H", yaw & 0xFFFF))
    body.extend(struct.pack("<I", st & 0xFFFFFFFF))
    body.extend(struct.pack("<h", int(ddx * 1000) & 0xFFFF))
    body.extend(struct.pack("<h", int(ddz * 1000) & 0xFFFF))
    body.append(jump & 0xFF)
    body.append(slide & 0xFF)
    return bytes(body)

# ════════════════════════════════════════════════════════════════════
#  MAIN MOVEMENT LOOP
# ════════════════════════════════════════════════════════════════════
async def movement_loop(sock, ra, ukb, mc, state, stop_evt, squad_n, tag):
    build_packet, layouts_from_mask = _app()
    planner   = MovementPlanner()
    nr        = (await layouts_from_mask(mc))[1]
    loop      = asyncio.get_event_loop()
    next_tick = time.time(); sent = 0; logged_started = False
    state.my_pos = (128749, 15456, 590657)

    body_override = bytes.fromhex(MOVEMENT_BODY_OVERRIDE_HEX) if MOVEMENT_BODY_OVERRIDE_HEX else None
    full_override = bytes.fromhex(MOVEMENT_FULL_OVERRIDE_HEX) if MOVEMENT_FULL_OVERRIDE_HEX else None

    while not stop_evt.is_set():
        now = time.time()
        interval = MOVE_INTERVAL * random.uniform(0.92, 1.08)
        if now < next_tick:
            try:
                await asyncio.wait_for(stop_evt.wait(), timeout=next_tick - now); break
            except asyncio.TimeoutError: pass
            continue
        next_tick += interval
        if next_tick < now: next_tick = now + MOVE_INTERVAL

        # ── HOMER SKILL BLOCK — unchanged ─────────────────────────
        try:
            cur = state.get_render_pos()
            if state.has_server_pos and state.target_pos is not None and cur is not None:
                dx = state.target_pos[0]-cur[0]; dy = state.target_pos[1]-cur[1]; dz = state.target_pos[2]-cur[2]
                dist = math.sqrt(dx*dx + dy*dy + dz*dz)
                if SKILL_RANGE_MIN <= dist <= SKILL_RANGE_MAX and state.homer.should_cast(now, state.joined_at):
                    st_tick = state.server_time(now)
                    state.homer.set_aim_direction(dx, dy, dz)
                    cast_pid = state.effective_pid()
                    short_sid = state.target_fid & 0xFF
                    for target_variant in (short_sid, state.target_fid):
                        body = state.homer.build_packet_body(cast_pid, st_tick, target_id=target_variant)
                        for cmd in (1412, 1414, CMD_USE_ACTIVE_SKILL, 250):
                            pkt = await build_packet(0x6B, nr, 0, cmd, None, 1, body, ukb, True)
                            await loop.sock_sendto(sock, pkt, ra)
                        await asyncio.sleep(0.015)
                    state.homer.mark_cast(now, state.homer.skill_id)
                    squad_ok(squad_n, f"{tag} 🎯 SKILL#{state.homer.fire_count} id={state.homer.skill_id} → fid=0x{state.target_fid:X} d={dist:.0f}")
        except Exception as e: dbg("ERROR", f"{tag} skill: {e}")

        # ── MOVEMENT BLOCK — with override ────────────────────────
        try:
            new_pos, ddx, ddz, dist = planner.plan(state, now)
            state.advance_pos(ddx, ddz)
            st     = state.server_time(now)
            yaw    = planner.next_yaw()
            pid    = state.effective_pid()
            render = state.get_render_pos()
            jump   = 1 if random.random() < 0.03 else 0
            slide  = 1 if (not jump and random.random() < 0.01) else 0

            if full_override is not None:
                pkt = full_override
            else:
                body = body_override if body_override is not None else \
                       _build_position_body(pid, render, yaw, st, ddx, ddz, jump, slide)
                pkt = await build_packet(0x6B, nr, 0, CMD_MY_STATE, None, 1, body, ukb, True)

            await loop.sock_sendto(sock, pkt, ra); sent += 1

            if not logged_started:
                logged_started = True
                squad_ok(squad_n, f"{tag} movement started (BR-Safe Mode)")
        except Exception as e: _udp_log(f"{tag} move err: {e}")

    dbg("SUMMARY", f"{tag} fires={state.homer.fire_count} pkts={sent}")