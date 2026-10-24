#!/usr/bin/env python3
"""Local Orange Tennis Club demo. Serves the site and stores bookings."""

import hashlib
import hmac
import json
import os
import posixpath
import secrets
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

HOST = "127.0.0.1"
PORT = 8080
ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(ROOT, "data.json")
ORIGIN = "http://127.0.0.1:8080"
SESSION_TTL = 12 * 60 * 60
PBKDF2_ROUNDS = 200_000
FOUNDING_BASE = 47
FOUNDING_CAP = 100

STAFF_USERNAME = "admin"
STAFF_SALT = "17e55f6361cc3af10a3820b2a8840a27"
STAFF_HASH = "d61b300828b99ad87807b66fb97a485ac4a4516dde2a8817a67ef0495ab536df"

COURTS = ["Kort 1", "Kort 2", "Kort 3", "Kort 4", "Kort 5"]
DAYS = ["Pzt 23", "Sal 24", "Çar 25", "Per 26", "Cum 27", "Cmt 28", "Paz 29"]
PRICES = {
    "08:00": 600,
    "09:30": 600,
    "11:00": 600,
    "12:30": 700,
    "14:00": 700,
    "15:30": 700,
    "17:00": 800,
    "18:30": 800,
    "20:00": 800,
    "21:30": 800,
}
ALL_TIMES = (
    "08:00", "09:30", "11:00", "12:30", "14:00",
    "15:30", "17:00", "18:30", "20:00", "21:30",
)
PACKAGES = (
    "Bireysel — 2.400 ₺/ay",
    "Aile — 3.800 ₺/ay",
    "Kurumsal — Teklif alın",
    "Henüz emin değilim",
)
LEVELS = ("Başlangıç", "Orta", "İleri", "Turnuva / Profesyonel")
ACTIVE = ("pending", "confirmed")

LOCK = threading.Lock()
SESSIONS = {}


def staff_record():
    return {
        "username": STAFF_USERNAME,
        "salt": STAFF_SALT,
        "passwordHash": STAFF_HASH,
    }


def fresh_data():
    return {
        "staff": staff_record(),
        "bookings": [],
        "applications": [],
        "takenSlots": [],
        "members": [],
    }


def write_data(data):
    tmp = DATA_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp, DATA_PATH)


def read_data():
    with open(DATA_PATH, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("data.json must be an object")
    data.setdefault("staff", staff_record())
    data.setdefault("bookings", [])
    data.setdefault("applications", [])
    data.setdefault("takenSlots", [])
    data.setdefault("members", [])
    return data


def ensure_data():
    if not os.path.exists(DATA_PATH):
        write_data(fresh_data())
        return
    with LOCK:
        with open(DATA_PATH, encoding="utf-8") as handle:
            raw = json.load(handle)
        data = read_data()
        changed = False
        if "staff" not in data or "passwordHash" not in data.get("staff", {}):
            data["staff"] = staff_record()
            changed = True
        for key in ("bookings", "applications", "takenSlots", "members"):
            if not isinstance(data.get(key), list):
                data[key] = []
                changed = True
        if "members" not in raw:
            data["members"] = []
            changed = True
        if changed:
            write_data(data)


def update(mutator):
    with LOCK:
        data = read_data()
        result = mutator(data)
        write_data(data)
        return result


def founding_count(data):
    return min(FOUNDING_BASE + len(data["applications"]), FOUNDING_CAP)


def same_slot(item, court, day, time_value):
    return item.get("court") == court and item.get("day") == day and item.get("time") == time_value


def slot_taken(data, court, day, time_value):
    for slot in data["takenSlots"]:
        if same_slot(slot, court, day, time_value):
            return True
    for booking in data["bookings"]:
        if booking.get("status") in ACTIVE and same_slot(booking, court, day, time_value):
            return True
    return False


def check_password(password, salt_hex, hash_hex):
    try:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS
    )
    return hmac.compare_digest(digest, expected)


def safe_eq(left, right):
    if len(left) != len(right):
        return False
    return hmac.compare_digest(left, right)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def clean_path(self):
        path = posixpath.normpath(unquote(urlparse(self.path).path))
        if not path.startswith("/"):
            path = "/" + path
        return path

    def is_private(self, path):
        base = posixpath.basename(path)
        return base == "server.py" or base.startswith("data.json")

    def origin_ok(self):
        origin = self.headers.get("Origin")
        if origin and origin.rstrip("/") != ORIGIN:
            return False
        referer = self.headers.get("Referer")
        if referer and referer != ORIGIN and not referer.startswith(ORIGIN + "/"):
            return False
        return True

    def session_token(self):
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            part = part.strip()
            if part.startswith("session="):
                return part.split("=", 1)[1]
        return ""

    def session(self):
        token = self.session_token()
        if not token:
            return None
        now = time.time()
        with LOCK:
            record = SESSIONS.get(token)
            if not isinstance(record, dict) or record.get("exp", 0) < now:
                SESSIONS.pop(token, None)
                return None
            return {"role": record.get("role"), "memberId": record.get("memberId")}

    def issue_session(self, role, member_id=None):
        token = secrets.token_urlsafe(32)
        with LOCK:
            SESSIONS[token] = {
                "role": role,
                "memberId": member_id,
                "exp": time.time() + SESSION_TTL,
            }
        return f"session={token}; HttpOnly; Path=/; SameSite=Lax; Max-Age={SESSION_TTL}"

    def drain(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return
        if 0 < length <= 100_000:
            self.rfile.read(length)

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        if length < 0 or length > 100_000:
            return None
        if length == 0:
            return {}
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        return data

    def send_json(self, code, payload, cookie=None, clear_cookie=False):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        if clear_cookie:
            self.send_header(
                "Set-Cookie",
                "session=; HttpOnly; Path=/; SameSite=Lax; Max-Age=0",
            )
        self.end_headers()
        self.wfile.write(body)

    def redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def serve_html(self, filename):
        with open(os.path.join(ROOT, filename), "rb") as handle:
            body = handle.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.clean_path()
        if self.is_private(path):
            return self.send_json(404, {"error": "Bulunamadı."})
        if path.startswith("/api/") and not self.origin_ok():
            return self.send_json(403, {"error": "Kaynak reddedildi."})
        if path == "/api/availability":
            return self.availability()
        if path == "/api/founding-count":
            return self.founding()
        if path == "/api/me":
            return self.whoami()
        if path == "/api/account":
            return self.account()
        if path == "/api/admin":
            record = self.session()
            if not record:
                return self.send_json(401, {"error": "Giriş gerekli."})
            if record.get("role") != "staff":
                return self.send_json(403, {"error": "Yetkisiz."})
            return self.admin_data()
        if path in ("/admin", "/admin.html"):
            record = self.session()
            if not record:
                return self.redirect("/login")
            if record.get("role") != "staff":
                return self.redirect("/hesap")
            return self.serve_html("admin.html")
        if path in ("/hesap", "/hesap.html"):
            record = self.session()
            if not record:
                return self.redirect("/login")
            if record.get("role") != "member":
                return self.redirect("/admin")
            return self.serve_html("hesap.html")
        if path in ("/kayit", "/kayit.html"):
            return self.serve_html("kayit.html")
        if path in ("/login", "/login.html"):
            return self.serve_html("login.html")
        return super().do_GET()

    def do_POST(self):
        path = self.clean_path()
        if not self.origin_ok():
            self.drain()
            return self.send_json(403, {"error": "Kaynak reddedildi."})
        if path == "/api/logout":
            self.drain()
            return self.logout()
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            self.drain()
            return self.send_json(400, {"error": "JSON gerekli."})
        body = self.read_json()
        if body is None:
            return self.send_json(400, {"error": "Geçersiz istek."})
        if path == "/api/login":
            return self.login(body)
        if path == "/api/signup":
            return self.signup(body)
        if path == "/api/bookings":
            return self.add_booking(body)
        if path == "/api/applications":
            return self.add_application(body)
        if path == "/api/bookings/status":
            return self.set_status(body)
        if path == "/api/slots/taken":
            return self.take_slot(body)
        return self.send_json(404, {"error": "Bulunamadı."})

    def login(self, body):
        identifier = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")
        with LOCK:
            data = read_data()
        staff = data["staff"]
        staff_user = safe_eq(identifier, str(staff.get("username") or ""))
        staff_pass = check_password(
            password, str(staff.get("salt") or ""), str(staff.get("passwordHash") or "")
        )
        if staff_user and staff_pass:
            return self.send_json(
                200, {"ok": True, "role": "staff"}, cookie=self.issue_session("staff")
            )
        member = None
        for item in data.get("members", []):
            if str(item.get("eposta") or "").lower() == identifier.lower():
                member = item
                break
        if member and check_password(
            password, str(member.get("salt") or ""), str(member.get("passwordHash") or "")
        ):
            return self.send_json(
                200,
                {"ok": True, "role": "member"},
                cookie=self.issue_session("member", member.get("id")),
            )
        if member is None:
            check_password(
                password, str(staff.get("salt") or ""), str(staff.get("passwordHash") or "")
            )
        return self.send_json(401, {"error": "Kullanıcı adı veya şifre hatalı."})

    def signup(self, body):
        ad = str(body.get("ad") or "").strip()
        soyad = str(body.get("soyad") or "").strip()
        telefon = str(body.get("telefon") or "").strip()
        eposta = str(body.get("eposta") or "").strip()
        password = str(body.get("password") or "")
        if not ad or not soyad or not telefon or not eposta or not password:
            return self.send_json(400, {"error": "Lütfen tüm alanları doldurun."})
        if len(ad) > 80 or len(soyad) > 80 or len(telefon) > 40 or len(eposta) > 120:
            return self.send_json(400, {"error": "Lütfen tüm alanları doldurun."})
        if len(password) < 6 or len(password) > 80:
            return self.send_json(400, {"error": "Şifre en az 6 karakter olmalı."})
        domain = eposta.split("@")[-1] if "@" in eposta else ""
        if "@" not in eposta or "." not in domain:
            return self.send_json(400, {"error": "E-posta geçersiz."})
        created = {}

        def mutate(data):
            for item in data["members"]:
                if str(item.get("eposta") or "").lower() == eposta.lower():
                    created["error"] = "Bu e-posta ile kayıt var."
                    return
            salt = secrets.token_hex(16)
            digest = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ROUNDS
            ).hex()
            member = {
                "id": secrets.token_hex(4),
                "ad": ad,
                "soyad": soyad,
                "telefon": telefon,
                "eposta": eposta,
                "salt": salt,
                "passwordHash": digest,
            }
            data["members"].append(member)
            created["member"] = member

        update(mutate)
        if "member" not in created:
            return self.send_json(409, {"error": created.get("error") or "Kaydedilemedi."})
        member = created["member"]
        return self.send_json(
            200,
            {"ok": True, "role": "member"},
            cookie=self.issue_session("member", member["id"]),
        )

    def whoami(self):
        record = self.session()
        if not record or record.get("role") not in ("staff", "member"):
            return self.send_json(200, {"role": None})
        if record.get("role") == "staff":
            return self.send_json(200, {"role": "staff"})
        with LOCK:
            members = read_data().get("members", [])
        member = next((item for item in members if item.get("id") == record.get("memberId")), None)
        if not member:
            return self.send_json(200, {"role": None})
        return self.send_json(200, {
            "role": "member",
            "ad": member.get("ad"),
            "soyad": member.get("soyad"),
            "eposta": member.get("eposta"),
            "telefon": member.get("telefon"),
        })

    def account(self):
        record = self.session()
        if not record:
            return self.send_json(401, {"error": "Giriş gerekli."})
        if record.get("role") != "member":
            return self.send_json(403, {"error": "Yetkisiz."})
        with LOCK:
            data = read_data()
        member = next(
            (item for item in data.get("members", []) if item.get("id") == record.get("memberId")),
            None,
        )
        if not member:
            return self.send_json(401, {"error": "Giriş gerekli."})
        bookings = [
            {
                "court": item.get("court"),
                "day": item.get("day"),
                "time": item.get("time"),
                "status": item.get("status"),
                "price": item.get("price"),
            }
            for item in data["bookings"]
            if item.get("memberId") == member["id"]
        ]
        return self.send_json(200, {
            "ad": member.get("ad"),
            "soyad": member.get("soyad"),
            "eposta": member.get("eposta"),
            "telefon": member.get("telefon"),
            "bookings": bookings,
        })

    def logout(self):
        token = self.session_token()
        if token:
            with LOCK:
                SESSIONS.pop(token, None)
        return self.send_json(200, {"ok": True}, clear_cookie=True)

    def availability(self):
        query = parse_qs(urlparse(self.path).query)
        want_court = (query.get("court") or [""])[0]
        want_day = (query.get("day") or [""])[0]
        with LOCK:
            data = read_data()
        blocked = []
        seen = set()

        def add(court, day, time_value):
            if want_court and court != want_court:
                return
            if want_day and day != want_day:
                return
            key = (court, day, time_value)
            if key in seen or not court or not day or not time_value:
                return
            seen.add(key)
            blocked.append({"court": court, "day": day, "time": time_value})

        for slot in data["takenSlots"]:
            add(slot.get("court"), slot.get("day"), slot.get("time"))
        for booking in data["bookings"]:
            if booking.get("status") in ACTIVE:
                add(booking.get("court"), booking.get("day"), booking.get("time"))
        return self.send_json(200, {"blocked": blocked})

    def founding(self):
        with LOCK:
            count = founding_count(read_data())
        return self.send_json(200, {"count": count, "remaining": FOUNDING_CAP - count})

    def admin_data(self):
        with LOCK:
            data = read_data()
            payload = {
                "bookings": list(data["bookings"]),
                "applications": list(data["applications"]),
                "takenSlots": list(data["takenSlots"]),
                "count": founding_count(data),
            }
        return self.send_json(200, payload)

    def add_booking(self, body):
        record = self.session()
        if not record or record.get("role") != "member" or not record.get("memberId"):
            return self.send_json(401, {"error": "Giriş gerekli."})
        member_id = record["memberId"]
        court = str(body.get("court") or "")
        day = str(body.get("day") or "")
        time_value = str(body.get("time") or "")
        try:
            price = int(body.get("price"))
        except (TypeError, ValueError):
            return self.send_json(400, {"error": "Eksik bilgi."})
        if court not in COURTS or day not in DAYS or time_value not in PRICES:
            return self.send_json(400, {"error": "Geçersiz kort, gün veya saat."})
        if price != PRICES[time_value]:
            return self.send_json(400, {"error": "Geçersiz ücret."})

        created = {}

        def mutate(data):
            member = next((item for item in data.get("members", []) if item.get("id") == member_id), None)
            if not member:
                created["error"] = "auth"
                return
            if slot_taken(data, court, day, time_value):
                created["error"] = "Bu saat dolu."
                return
            booking = {
                "id": secrets.token_hex(4),
                "court": court,
                "day": day,
                "time": time_value,
                "price": price,
                "status": "pending",
                "memberId": member["id"],
                "memberName": (str(member.get("ad") or "") + " " + str(member.get("soyad") or "")).strip(),
            }
            data["bookings"].append(booking)
            created["booking"] = booking

        update(mutate)
        if created.get("error") == "auth":
            return self.send_json(401, {"error": "Giriş gerekli."})
        if "error" in created:
            return self.send_json(409, {"error": created["error"]})
        return self.send_json(200, {"ok": True, "booking": created["booking"]})

    def add_application(self, body):
        limits = {
            "ad": 80,
            "soyad": 80,
            "telefon": 40,
            "eposta": 120,
            "paket": 80,
            "seviye": 80,
        }
        fields = {}
        for key, limit in limits.items():
            value = str(body.get(key) or "").strip()
            if not value or len(value) > limit:
                return self.send_json(400, {"error": "Lütfen tüm alanları doldurun."})
            fields[key] = value
        domain = fields["eposta"].split("@")[-1] if "@" in fields["eposta"] else ""
        if "@" not in fields["eposta"] or "." not in domain:
            return self.send_json(400, {"error": "E-posta geçersiz."})
        if fields["paket"] not in PACKAGES or fields["seviye"] not in LEVELS:
            return self.send_json(400, {"error": "Geçersiz paket veya seviye."})

        saved = {}

        def mutate(data):
            record = {"id": secrets.token_hex(4), **fields}
            data["applications"].append(record)
            saved["count"] = founding_count(data)

        update(mutate)
        count = saved["count"]
        return self.send_json(200, {"ok": True, "count": count, "remaining": FOUNDING_CAP - count})

    def set_status(self, body):
        record = self.session()
        if not record:
            return self.send_json(401, {"error": "Giriş gerekli."})
        if record.get("role") != "staff":
            return self.send_json(403, {"error": "Yetkisiz."})
        booking_id = str(body.get("id") or "")
        status = str(body.get("status") or "")
        if status not in ("confirmed", "cancelled"):
            return self.send_json(400, {"error": "Geçersiz durum."})
        found = {}

        def mutate(data):
            for booking in data["bookings"]:
                if booking.get("id") != booking_id:
                    continue
                if status == "confirmed" and slot_taken(
                    {
                        "takenSlots": data["takenSlots"],
                        "bookings": [
                            item for item in data["bookings"] if item.get("id") != booking_id
                        ],
                    },
                    booking.get("court"),
                    booking.get("day"),
                    booking.get("time"),
                ):
                    found["error"] = "Bu saat dolu."
                    return
                booking["status"] = status
                found["booking"] = {
                    "id": booking["id"],
                    "court": booking["court"],
                    "day": booking["day"],
                    "time": booking["time"],
                    "price": booking["price"],
                    "status": booking["status"],
                }
                return
            found["error"] = "Rezervasyon bulunamadı."

        update(mutate)
        if "booking" not in found:
            code = 409 if found.get("error") == "Bu saat dolu." else 404
            return self.send_json(code, {"error": found.get("error") or "Kaydedilemedi."})
        return self.send_json(200, {"ok": True, "booking": found["booking"]})

    def take_slot(self, body):
        record = self.session()
        if not record:
            return self.send_json(401, {"error": "Giriş gerekli."})
        if record.get("role") != "staff":
            return self.send_json(403, {"error": "Yetkisiz."})
        court = str(body.get("court") or "")
        day = str(body.get("day") or "")
        time_value = str(body.get("time") or "")
        if court not in COURTS or day not in DAYS or time_value not in ALL_TIMES:
            return self.send_json(400, {"error": "Geçersiz kort, gün veya saat."})
        state = {}

        def mutate(data):
            for slot in data["takenSlots"]:
                if same_slot(slot, court, day, time_value):
                    state["already"] = True
                    return
            data["takenSlots"].append(
                {"court": court, "day": day, "time": time_value}
            )
            state["already"] = False

        update(mutate)
        return self.send_json(200, {"ok": True, "already": state["already"]})


class Server(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    ensure_data()
    httpd = Server((HOST, PORT), Handler)
    print(f"Serving http://{HOST}:{PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
