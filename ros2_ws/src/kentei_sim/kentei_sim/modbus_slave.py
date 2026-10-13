"""依存ライブラリなしの最小 Modbus/TCP スレーブ.

OpenPLC (マスタ) からのポーリングに応答する。
  - ディスクリート入力 (FC2 読み出し): 検定くん -> PLC の入力 (押しボタン・センサ)
  - コイル (FC5/FC15 書き込み, FC1 読み出し): PLC -> 検定くん の出力 (ランプ・ソレノイド)
"""

import socketserver
import struct
import threading
import time
from typing import Callable, List, Optional

READ_COILS = 1
READ_DISCRETE_INPUTS = 2
WRITE_SINGLE_COIL = 5
WRITE_MULTIPLE_COILS = 15

ILLEGAL_FUNCTION = 1
ILLEGAL_DATA_ADDRESS = 2
ILLEGAL_DATA_VALUE = 3

MAX_READ_BITS = 2000
MAX_WRITE_BITS = 1968


def pack_bits(bits: List[bool]) -> bytes:
    out = bytearray((len(bits) + 7) // 8)
    for i, b in enumerate(bits):
        if b:
            out[i // 8] |= 1 << (i % 8)
    return bytes(out)


def unpack_bits(data: bytes, count: int) -> List[bool]:
    return [bool(data[i // 8] >> (i % 8) & 1) for i in range(count)]


class BitStore:
    """入力・出力ビットのスレッドセーフな保持."""

    def __init__(self, input_size: int, output_size: int):
        self._lock = threading.Lock()
        self._inputs = [False] * input_size
        self._coils = [False] * output_size
        self.on_coils_changed: Optional[Callable[[List[bool]], None]] = None

    @property
    def input_size(self) -> int:
        return len(self._inputs)

    @property
    def output_size(self) -> int:
        return len(self._coils)

    def set_input(self, bit: int, value: bool) -> None:
        with self._lock:
            self._inputs[bit] = bool(value)

    def get_input(self, bit: int) -> bool:
        with self._lock:
            return self._inputs[bit]

    def inputs(self) -> List[bool]:
        with self._lock:
            return list(self._inputs)

    def coils(self) -> List[bool]:
        with self._lock:
            return list(self._coils)

    def read_inputs(self, start: int, count: int) -> List[bool]:
        with self._lock:
            return self._inputs[start:start + count]

    def read_coils(self, start: int, count: int) -> List[bool]:
        with self._lock:
            return self._coils[start:start + count]

    def write_coils(self, start: int, values: List[bool]) -> None:
        with self._lock:
            changed = self._coils[start:start + len(values)] != values
            self._coils[start:start + len(values)] = values
            snapshot = list(self._coils)
        if changed and self.on_coils_changed:
            self.on_coils_changed(snapshot)


def handle_pdu(store: BitStore, pdu: bytes) -> bytes:
    """リクエスト PDU を処理してレスポンス PDU を返す."""
    if not pdu:
        return bytes([0x80, ILLEGAL_FUNCTION])
    fc = pdu[0]

    def error(code: int) -> bytes:
        return bytes([fc | 0x80, code])

    if fc in (READ_COILS, READ_DISCRETE_INPUTS):
        if len(pdu) != 5:
            return error(ILLEGAL_DATA_VALUE)
        start, count = struct.unpack('>HH', pdu[1:5])
        if not 1 <= count <= MAX_READ_BITS:
            return error(ILLEGAL_DATA_VALUE)
        size = store.output_size if fc == READ_COILS else store.input_size
        if start + count > size:
            return error(ILLEGAL_DATA_ADDRESS)
        bits = store.read_coils(start, count) if fc == READ_COILS else store.read_inputs(start, count)
        data = pack_bits(bits)
        return bytes([fc, len(data)]) + data

    if fc == WRITE_SINGLE_COIL:
        if len(pdu) != 5:
            return error(ILLEGAL_DATA_VALUE)
        addr, value = struct.unpack('>HH', pdu[1:5])
        if value not in (0x0000, 0xFF00):
            return error(ILLEGAL_DATA_VALUE)
        if addr >= store.output_size:
            return error(ILLEGAL_DATA_ADDRESS)
        store.write_coils(addr, [value == 0xFF00])
        return pdu

    if fc == WRITE_MULTIPLE_COILS:
        if len(pdu) < 6:
            return error(ILLEGAL_DATA_VALUE)
        start, count, nbytes = struct.unpack('>HHB', pdu[1:6])
        if not 1 <= count <= MAX_WRITE_BITS or nbytes != (count + 7) // 8 or len(pdu) != 6 + nbytes:
            return error(ILLEGAL_DATA_VALUE)
        if start + count > store.output_size:
            return error(ILLEGAL_DATA_ADDRESS)
        store.write_coils(start, unpack_bits(pdu[6:], count))
        return pdu[:5]

    return error(ILLEGAL_FUNCTION)


def _recv_exact(sock, n: int) -> Optional[bytes]:
    buf = b''
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        server: 'ModbusTcpSlave' = self.server  # type: ignore[assignment]
        while True:
            header = _recv_exact(self.request, 7)
            if header is None:
                return
            tid, pid, length, unit = struct.unpack('>HHHB', header)
            if pid != 0 or not 2 <= length <= 254:
                return
            pdu = _recv_exact(self.request, length - 1)
            if pdu is None:
                return
            # unit id 0 / 255 は TCP では「任意」として扱う
            if unit not in (server.unit_id, 0, 255):
                continue
            server.last_request = time.monotonic()
            resp = handle_pdu(server.store, pdu)
            self.request.sendall(struct.pack('>HHHB', tid, 0, len(resp) + 1, unit) + resp)


class ModbusTcpSlave(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, store: BitStore, host: str = '0.0.0.0', port: int = 5020, unit_id: int = 1):
        self.store = store
        self.unit_id = unit_id
        self.last_request = float('-inf')  # 最後にリクエストを受けた time.monotonic()
        super().__init__((host, port), _Handler)

    def start(self) -> threading.Thread:
        t = threading.Thread(target=self.serve_forever, name='modbus-slave', daemon=True)
        t.start()
        return t

    def stop(self) -> None:
        self.shutdown()
        self.server_close()
