# -*- coding: utf-8 -*-
"""
FreeFire Level Up Bot - Professional Web Dashboard & Real-Time EXP Tracker
Embedded Async Web Server (aiohttp)
"""

import asyncio
import json
import os
import time
from typing import Dict, List, Any, Optional
from aiohttp import web

# Game modes extracted from Free Fire client IL2CPP dump (tcp.EMatch.GameMode & MatchMode)
GAME_MODES: Dict[str, Dict[str, Any]] = {
    "lone_wolf_1v1": {
        "name": "Lone Wolf 1v1",
        "game_mode": 43, # GameMode_LoneWolfStrikeOut
        "match_mode": 1, # MatchMode_CASUAL
        "group_mode": 1, # Solo
        "map_id": 11,
        "description": "Fast 1v1 Duel (Fastest Level Up)"
    },
    "lone_wolf_2v2": {
        "name": "Lone Wolf 2v2",
        "game_mode": 63, # GameMode_LoneWolfMulti
        "match_mode": 1, # MatchMode_CASUAL
        "group_mode": 2, # Duo
        "map_id": 11,
        "description": "2v2 Duo Lone Wolf"
    },
    "craftland": {
        "name": "Craftland (UGC)",
        "game_mode": 41, # GameMode_UGC
        "match_mode": 8, # MatchMode_UGC
        "group_mode": 1,
        "map_id": 1,
        "description": "Custom UGC Fast EXP Maps"
    },
    "clash_squad": {
        "name": "Clash Squad (Normal)",
        "game_mode": 15, # GameMode_CS (verified from cs.py)
        "match_mode": 1, # MatchMode_CASUAL
        "group_mode": 1, # Solo Matchmaking (from cs.py CS_Solo_Start_Matchmaking_Packet)
        "map_id": 1,     # Bermuda CS (Map 1 from cs.py)
        "description": "4v4 Casual Combat"
    },
    "clash_squad_ranked": {
        "name": "Clash Squad (Ranked)",
        "game_mode": 15, # GameMode_CS (verified from cs.py)
        "match_mode": 6, # MatchMode_CSRANKING
        "group_mode": 1, # Solo Matchmaking (from cs.py CS_Solo_Start_Matchmaking_Packet)
        "map_id": 1,     # Bermuda CS (Map 1 from cs.py)
        "description": "4v4 CS Ranked"
    },
    "training": {
        "name": "Training Ground",
        "game_mode": 19, # GameMode_Training
        "match_mode": 5, # MatchMode_TRAINING
        "group_mode": 1,
        "map_id": 1,
        "description": "Combat Training Zone"
    },
    "battle_royale": {
        "name": "Battle Royale",
        "game_mode": 1, # GameMode_BattleRoyale
        "match_mode": 1, # MatchMode_CASUAL
        "group_mode": 1, # Solo
        "map_id": 1,
        "description": "50-Player Classic BR"
    },
    "br_ranked": {
        "name": "Battle Royale (Ranked)",
        "game_mode": 1, # GameMode_BattleRoyale
        "match_mode": 2, # MatchMode_RANKING (BR Ranked)
        "group_mode": 1, # Solo
        "map_id": 1,
        "description": "50-Player BR Ranked Mode"
    }
}

        # Global bot state shared between Main.py and Web Dashboard
class BotState:
    def __init__(self):
        self.accounts: Dict[str, Dict[str, Any]] = {}
        self.logs: List[Dict[str, Any]] = []
        self.max_logs = 200
        self.total_matches = 0
        self.total_gained_exp = 0
        self.start_time = time.time()
        self.account_workers: Dict[str, asyncio.Task] = {}
        self.refresh_callbacks: Dict[str, Any] = {}
        self.account_credentials: Dict[str, Dict[str, Any]] = {}
        self.wake_events: Dict[str, asyncio.Event] = {}
        self.global_game_mode: str = "battle_royale"
        # 🔥 Tracks UIDs deleted from web — stops all running tasks for that UID
        self.deleted_uids: set = set()
        # 🔥 Aliases mapping between auth_uid (guest login) and in-game account_id
        self.uid_aliases: Dict[str, str] = {}

    def register_alias(self, alias_uid: str, canonical_uid: str):
        if alias_uid and canonical_uid:
            a = str(alias_uid).strip()
            c = str(canonical_uid).strip()
            self.uid_aliases[a] = c
            # Reverse-link alias back to account record if existing
            if c in self.accounts and a not in self.accounts:
                self.uid_aliases[a] = c

    def resolve_uid(self, uid: Any) -> str:
        s = str(uid).strip()
        return self.uid_aliases.get(s, s)

    def set_global_mode(self, mode: str) -> bool:
        if mode in GAME_MODES:
            self.global_game_mode = mode
            for acc in self.accounts.values():
                acc["mode"] = mode
                acc["mode_name"] = GAME_MODES[mode]["name"]
            self.log(f"Global Game Mode switched to {GAME_MODES[mode]['name']}", "info")
            return True
        return False

    def log(self, message: str, level: str = "info", uid: Optional[str] = None):
        resolved = self.resolve_uid(uid) if uid else None
        entry = {
            "time": time.strftime("%H:%M:%S"),
            "level": level,
            "message": message,
            "uid": resolved or uid
        }
        self.logs.append(entry)
        if len(self.logs) > self.max_logs:
            self.logs.pop(0)

    def register_account(self, uid: str, nickname: str = "", region: str = "", level: int = 1, exp: int = 0, likes: int = 0, proxy: Optional[str] = None, mode: Optional[str] = None, auth_uid: Optional[str] = None):
        raw_uid = str(uid).strip()
        auth_uid_clean = str(auth_uid).strip() if auth_uid else None

        # 🔥 Clear deleted state so active/re-added accounts are never blocked
        self.deleted_uids.discard(raw_uid)
        if auth_uid_clean:
            self.deleted_uids.discard(auth_uid_clean)

        # 🔥 CRITICAL FIX: If registering real in-game account_id with auth_uid alias,
        # remove the pre-login temporary placeholder card from self.accounts!
        old_acc = None
        if auth_uid_clean and auth_uid_clean != raw_uid:
            self.register_alias(auth_uid_clean, raw_uid)
            if auth_uid_clean in self.accounts:
                old_acc = self.accounts.pop(auth_uid_clean, None)

        uid_str = self.resolve_uid(raw_uid)
        self.deleted_uids.discard(uid_str)

        active_mode = mode or (old_acc.get("mode") if old_acc else None) or self.global_game_mode
        mode_name = GAME_MODES.get(active_mode, {}).get("name", active_mode)
        resolved_region = region or (old_acc.get("region") if old_acc and old_acc.get("region") != "BD" else "") or "IND"

        if uid_str not in self.accounts:
            self.accounts[uid_str] = {
                "uid": uid_str,
                "auth_uid": auth_uid_clean or uid_str,
                "nickname": nickname or f"Player_{uid_str[:6]}",
                "region": resolved_region,
                "level": level or (old_acc.get("level", 1) if old_acc else 1),
                "initial_exp": exp or (old_acc.get("initial_exp", 0) if old_acc else 0),
                "current_exp": exp or (old_acc.get("current_exp", 0) if old_acc else 0),
                "gained_exp": old_acc.get("gained_exp", 0) if old_acc else 0,
                "likes": likes or (old_acc.get("likes", 0) if old_acc else 0),
                "proxy": proxy or (old_acc.get("proxy", "") if old_acc else ""),
                "mode": active_mode,
                "mode_name": mode_name,
                "status": old_acc.get("status", "ONLINE") if old_acc else "ONLINE",
                "matches_played": old_acc.get("matches_played", 0) if old_acc else 0,
                "active_matches": old_acc.get("active_matches", 0) if old_acc else 0,
                "last_match_time": old_acc.get("last_match_time") if old_acc else None,
                "last_updated": time.strftime("%H:%M:%S")
            }
        else:
            acc = self.accounts[uid_str]
            if auth_uid_clean:
                acc["auth_uid"] = auth_uid_clean
            if nickname:
                acc["nickname"] = nickname
            if region:
                acc["region"] = region
            if level:
                acc["level"] = level
            if proxy:
                acc["proxy"] = proxy
            if mode:
                acc["mode"] = mode
                acc["mode_name"] = mode_name
            elif not acc.get("mode"):
                acc["mode"] = self.global_game_mode
                acc["mode_name"] = GAME_MODES.get(self.global_game_mode, {}).get("name", self.global_game_mode)
            if exp > 0:
                if acc.get("initial_exp", 0) == 0:
                    acc["initial_exp"] = exp
                acc["current_exp"] = exp
                acc["gained_exp"] = max(0, exp - acc["initial_exp"])
            if likes:
                acc["likes"] = likes
            acc["last_updated"] = time.strftime("%H:%M:%S")
        self.recalc_totals()

    def update_exp(self, uid: str, current_exp: int, level: Optional[int] = None):
        uid_str = self.resolve_uid(uid)
        if uid_str in self.accounts:
            acc = self.accounts[uid_str]
            old_exp = acc["current_exp"]
            if acc.get("initial_exp", 0) == 0 and current_exp > 0:
                acc["initial_exp"] = current_exp
            acc["current_exp"] = current_exp
            if level is not None and level > 0:
                acc["level"] = level
            acc["gained_exp"] = max(0, current_exp - acc["initial_exp"])
            acc["last_updated"] = time.strftime("%H:%M:%S")
            diff = current_exp - old_exp
            if diff > 0:
                self.log(f"Account {acc['nickname']} ({uid_str}) gained +{diff} EXP! Total Gained: +{acc['gained_exp']}", "success", uid_str)
            self.recalc_totals()

    def update_status(self, uid: str, status: str, active_matches: Optional[int] = None):
        uid_str = self.resolve_uid(uid)
        if uid_str in self.accounts:
            self.accounts[uid_str]["status"] = status
            if active_matches is not None:
                self.accounts[uid_str]["active_matches"] = active_matches
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")

    def increment_match(self, uid: str):
        uid_str = self.resolve_uid(uid)
        self.total_matches += 1
        if uid_str in self.accounts:
            self.accounts[uid_str]["matches_played"] += 1
            self.accounts[uid_str]["last_match_time"] = time.strftime("%H:%M:%S")
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")
            self.log(f"Account {self.accounts[uid_str]['nickname']} finished Match #{self.accounts[uid_str]['matches_played']}", "info", uid_str)

    def recalc_totals(self):
        self.total_gained_exp = sum(acc.get("gained_exp", 0) for acc in self.accounts.values())

    def set_account_sleep(self, uid: str, sleep_until: float, reason: str = "6-Hour Playtime Limit Reached"):
        uid_str = self.resolve_uid(uid)
        if uid_str in self.accounts:
            self.accounts[uid_str]["status"] = "LIMIT_REACHED"
            self.accounts[uid_str]["sleep_until"] = int(sleep_until)
            self.accounts[uid_str]["sleep_reason"] = reason
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")
            self.log(f"Account {self.accounts[uid_str].get('nickname', uid_str)} entered auto-sleep until {time.strftime('%H:%M:%S', time.localtime(sleep_until))} ({reason})", "warning", uid_str)

    def clear_account_sleep(self, uid: str):
        uid_str = self.resolve_uid(uid)
        if uid_str in self.accounts:
            self.accounts[uid_str]["status"] = "ONLINE"
            self.accounts[uid_str].pop("sleep_until", None)
            self.accounts[uid_str].pop("sleep_reason", None)
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")

    def wake_account(self, uid: str):
        uid_str = self.resolve_uid(uid)
        self.clear_account_sleep(uid_str)
        if uid_str in self.wake_events:
            self.wake_events[uid_str].set()
            self.log(f"Account {uid_str} manually awakened by user", "info", uid_str)
        if str(uid) in self.wake_events and str(uid) != uid_str:
            self.wake_events[str(uid)].set()

    def remove_account(self, uid: str):
        """Mark UID as deleted — stops all running match tasks for this account."""
        canonical = self.resolve_uid(uid)
        to_remove = {str(uid).strip(), canonical}
        for alias, target in list(self.uid_aliases.items()):
            if target in to_remove or alias in to_remove:
                to_remove.add(alias)
                to_remove.add(target)

        for u in to_remove:
            self.deleted_uids.add(u)
            if u in self.account_workers:
                try:
                    self.account_workers[u].cancel()
                except Exception:
                    pass
                del self.account_workers[u]
            self.accounts.pop(u, None)
            self.account_credentials.pop(u, None)

        self.log(f"Account {uid} removed and all tasks cancelled.", "warning", uid)
        print(f"\033[91m[-] [DASHBOARD] Account {uid} deleted — stopping all match tasks\033[0m")


bot_state = BotState()


# ==================== HTTP HANDLERS ====================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(BASE_DIR, "templates", "index.html")
ACCOUNTS_FILE = os.path.join(BASE_DIR, "accounts.json")

async def handle_index(request: web.Request) -> web.Response:
    if os.path.exists(TEMPLATE_PATH):
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        content = "<h1>templates/index.html not found!</h1>"
    return web.Response(text=content, content_type="text/html", charset="utf-8")


async def handle_get_stats(request: web.Request) -> web.Response:
    accounts_data = list(bot_state.accounts.values())
    accounts_data.sort(key=lambda x: x.get("gained_exp", 0), reverse=True)
    return web.json_response({
        "total_accounts": len(bot_state.accounts),
        "total_matches": bot_state.total_matches,
        "total_gained_exp": bot_state.total_gained_exp,
        "global_mode": bot_state.global_game_mode,
        "available_modes": GAME_MODES,
        "accounts": accounts_data,
        "logs": bot_state.logs[-60:],
        "uptime": int(time.time() - bot_state.start_time)
    })


async def handle_set_mode(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        mode = data.get("mode")
        uid = data.get("uid")
        if not mode or mode not in GAME_MODES:
            return web.json_response({"status": "error", "error": f"Invalid mode. Available: {list(GAME_MODES.keys())}"}, status=400)
        
        mode_title = GAME_MODES[mode]["name"]
        if uid:
            raw_uid = str(uid).strip()
            uid_str = bot_state.resolve_uid(raw_uid)
            for k in (raw_uid, uid_str):
                if k in bot_state.accounts:
                    bot_state.accounts[k]["mode"] = mode
                    bot_state.accounts[k]["mode_name"] = mode_title
                if k in bot_state.account_credentials:
                    bot_state.account_credentials[k]["mode"] = mode
            bot_state.log(f"Account {uid_str} mode set to {mode_title}", "info", uid_str)
            print(f"\033[96m[+] [DASHBOARD] Mode set to {mode_title} for UID {uid_str}\033[0m")
        else:
            bot_state.set_global_mode(mode)
            for acc in bot_state.accounts.values():
                acc["mode"] = mode
                acc["mode_name"] = mode_title
            for cred in bot_state.account_credentials.values():
                cred["mode"] = mode
            print(f"\033[96m[+] [DASHBOARD] Global Mode set to {mode_title} for all accounts\033[0m")

        return web.json_response({
            "status": "ok",
            "global_mode": bot_state.global_game_mode,
            "mode_name": mode_title
        })
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)}, status=500)


async def handle_add_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        accounts_file = ACCOUNTS_FILE
        existing = []
        if os.path.exists(accounts_file):
            try:
                with open(accounts_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = []

        proxy = str(data.get("proxy", "")).strip()
        mode = str(data.get("mode", "")).strip()

        if "uid" in data and "password" in data:
            uid = str(data["uid"]).strip()
            pwd = str(data["password"]).strip()
            if not uid or not pwd:
                return web.json_response({"status": "error", "error": "UID and Password are required"})
            existing = [acc for acc in existing if str(acc.get("uid")) != uid]
            item = {"uid": uid, "password": pwd}
            if proxy:
                item["proxy"] = proxy
            if mode and mode in GAME_MODES:
                item["mode"] = mode
            existing.append(item)
            # Unmark from deleted state
            bot_state.deleted_uids.discard(uid)
            canonical = bot_state.resolve_uid(uid)
            bot_state.deleted_uids.discard(canonical)
            for a, c in list(bot_state.uid_aliases.items()):
                if a in (uid, canonical) or c in (uid, canonical):
                    bot_state.deleted_uids.discard(a)
                    bot_state.deleted_uids.discard(c)
        elif "token" in data:
            token = str(data["token"]).strip()
            if not token:
                return web.json_response({"status": "error", "error": "Token is required"})
            existing = [acc for acc in existing if acc.get("token") != token]
            item = {"token": token}
            if proxy:
                item["proxy"] = proxy
            if mode and mode in GAME_MODES:
                item["mode"] = mode
            existing.append(item)
            bot_state.deleted_uids.discard(token)
            bot_state.deleted_uids.discard(f"tok_{token[:20]}")
        else:
            return web.json_response({"status": "error", "error": "Invalid payload"})

        with open(accounts_file, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)

        bot_state.log(f"New account added: {data.get('uid') or 'Token'}", "success")
        
        # Trigger dynamic worker launch
        if "on_account_added" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_account_added"](data))

        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_delete_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        raw_uid = str(data.get("uid")).strip()
        canonical_uid = bot_state.resolve_uid(raw_uid)
        to_del = {raw_uid, canonical_uid}
        for a, c in list(bot_state.uid_aliases.items()):
            if c in to_del or a in to_del:
                to_del.add(a)
                to_del.add(c)

        accounts_file = ACCOUNTS_FILE
        if os.path.exists(accounts_file):
            with open(accounts_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
            existing = [acc for acc in existing if str(acc.get("uid")) not in to_del]
            with open(accounts_file, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2)

        # 🔥 Use remove_account() which cancels ALL tasks and marks UID as deleted
        bot_state.remove_account(canonical_uid)
        for u in to_del:
            bot_state.remove_account(u)

        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_refresh_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        raw_uid = str(data.get("uid")).strip()
        uid = bot_state.resolve_uid(raw_uid)
        if "on_refresh_account" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_refresh_account"](uid))
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_wake_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        raw_uid = str(data.get("uid")).strip()
        uid = bot_state.resolve_uid(raw_uid)
        bot_state.wake_account(uid)
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_claim_rewards(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        raw_uid = str(data.get("uid")).strip()
        uid = bot_state.resolve_uid(raw_uid)
        if "on_claim_rewards" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_claim_rewards"](uid))
            return web.json_response({"status": "ok", "message": "Reward claim requested"})
        return web.json_response({"status": "error", "error": "Reward claim handler not active"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def start_web_dashboard(host: str = "0.0.0.0", port: int = 5000):
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/stats", handle_get_stats)
    app.router.add_post("/api/mode/set", handle_set_mode)
    app.router.add_post("/api/account/add", handle_add_account)
    app.router.add_post("/api/account/delete", handle_delete_account)
    app.router.add_post("/api/account/refresh", handle_refresh_account)
    app.router.add_post("/api/account/wake", handle_wake_account)
    app.router.add_post("/api/account/claim", handle_claim_rewards)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    print(f"\033[92m[+] Web Dashboard running on 0.0.0.0:{port} (All Interfaces)\033[0m")


if __name__ == "__main__":
    async def _dev_server():
        await start_web_dashboard(port=2003)
        bot_state.log("Dev Dashboard Server initialized", "info")
        while True:
            await asyncio.sleep(3600)
    try:
        asyncio.run(_dev_server())
    except KeyboardInterrupt:
        print("\n[!] Dashboard stopped.")
