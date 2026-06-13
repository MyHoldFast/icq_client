"""
reg.py — регистрация нового UIN на ICQ-сервере через OSCAR/SNAC.
Протокол: FLAP (TCP) + SNAC family 0x17, subtype 0x04.
"""
from __future__ import annotations

import asyncio
import logging
import struct
import time

log = logging.getLogger("icq_register")

DEFAULT_SERVER = "195.66.114.37"
DEFAULT_PORT   = 5190

SN_TYP_REGISTRATION = 0x0017
SN_IES_ERROR        = 0x0001
SN_IES_LOGINxREPLY  = 0x0003
SN_IES_REQxNEWxUIN  = 0x0004
SN_IES_SRVxNEWxUIN  = 0x0005


def _pack_flap(channel: int, seq: int, payload: bytes) -> bytes:
    return struct.pack("!BBHH", 0x2A, channel, seq & 0xFFFF, len(payload)) + payload


def _make_snac(fam: int, sub: int, flags: int = 0,
               reqid: int = 0, payload: bytes = b"") -> bytes:
    return struct.pack("!HHHI", fam, sub, flags, reqid) + payload


def _make_tlv(t: int, v: bytes) -> bytes:
    return struct.pack("!HH", t, len(v)) + v


def _parse_tlvs(data: bytes) -> dict:
    out, pos = {}, 0
    while pos + 4 <= len(data):
        t, l = struct.unpack_from("!HH", data, pos)
        pos += 4
        out[t] = data[pos:pos + l]
        pos += l
    return out


class ICQRegistration:
    def __init__(self, server: str = DEFAULT_SERVER, port: int = DEFAULT_PORT):
        self.server = server
        self.port   = port
        self._seq   = 0

    async def register(self, password: str, timeout: float = 15.0) -> int:
        """Возвращает новый UIN. Бросает RuntimeError при отказе сервера."""
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(self.server, self.port),
            timeout=timeout,
        )
        self._seq = int(time.time()) & 0xFFFF
        try:
            return await self._do_register(reader, writer, password, timeout)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _do_register(self, reader, writer, password: str, timeout: float) -> int:

        async def recv_flap():
            hdr = await asyncio.wait_for(reader.readexactly(6), timeout)
            _, ch, seq, size = struct.unpack("!BBHH", hdr)
            body = await reader.readexactly(size) if size else b""
            log.debug(f"← FLAP ch={ch} seq={seq} len={size}" +
                      (f" hex={body.hex()}" if size else ""))
            return ch, body

        def send_flap(channel: int, payload: bytes = b""):
            self._seq = (self._seq + 1) & 0xFFFF
            writer.write(_pack_flap(channel, self._seq, payload))
            log.debug(f"→ FLAP ch={channel} seq={self._seq} len={len(payload)}")

        # Шаг 1: server hello
        ch, body = await recv_flap()
        log.info(f"Server hello: ch={ch} body={body.hex()}")

        # Шаг 2: анонимный hello
        send_flap(1, b"\x00\x00\x00\x01")
        await writer.drain()

        # Шаг 3: SNAC(0x17, 0x04) — запрос нового UIN
        req_cookie = int(time.time()) & 0xFFFFFFFF
        pwd_bytes  = password.encode("ascii", errors="replace")[:19]
        inner  = struct.pack("<IIIIIIIIII", 0, 0, 0, 0, req_cookie, 0, 0, 0, 0, 0)
        inner += struct.pack("<H", len(pwd_bytes)) + pwd_bytes
        inner += struct.pack("<IHH", 0, 0, 0x0700)

        send_flap(2, _make_snac(SN_TYP_REGISTRATION, SN_IES_REQxNEWxUIN,
                                reqid=0, payload=_make_tlv(0x0001, inner)))
        await writer.drain()
        log.info("Отправлен SNAC(0x17, 0x04) — запрос регистрации")

        # Шаг 4: ждём SNAC(0x17, 0x05)
        for _ in range(10):
            ch, body = await recv_flap()

            if ch == 4:
                raise RuntimeError("Сервер закрыл соединение до выдачи UIN")
            if ch != 2 or len(body) < 10:
                continue

            fam, sub = struct.unpack_from("!HH", body, 0)

            if fam == SN_TYP_REGISTRATION and sub == SN_IES_ERROR:
                raise RuntimeError(
                    "Сервер отклонил регистрацию (SNAC 0x17/0x01). "
                    "Убедитесь что на сервере включена регистрация: v7 registration = yes"
                )

            if fam == SN_TYP_REGISTRATION and sub == SN_IES_LOGINxREPLY:
                tlvs = _parse_tlvs(body[10:])
                err  = tlvs.get(0x0008, b"")
                code = struct.unpack_from("!H", err)[0] if len(err) >= 2 else 0
                raise RuntimeError(
                    f"Сервер вернул ошибку логина (код={code:#06x}). "
                    "Сервер воспринял пакет как попытку входа."
                )

            if fam == SN_TYP_REGISTRATION and sub == SN_IES_SRVxNEWxUIN:
                tlvs = _parse_tlvs(body[10:])
                blob = tlvs.get(0x0001, b"")
                log.debug(f"TLV(0x01) len={len(blob)} hex={blob.hex()}")
                if len(blob) >= 44:
                    data = blob[2:]
                    if len(data) >= 44:
                        new_uin = struct.unpack_from("<I", data, 40)[0]
                        log.info(f"Получен новый UIN: {new_uin}")
                        return new_uin
                raise RuntimeError(
                    "SNAC(0x17, 0x05) получен, но UIN не распознан. "
                    "Включите debug-логирование для диагностики."
                )

        raise RuntimeError("Сервер не выдал UIN за 10 пакетов")
