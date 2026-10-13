import socket
import struct

import pytest

from kentei_sim.modbus_slave import BitStore, ModbusTcpSlave, handle_pdu, pack_bits, unpack_bits


def test_pack_unpack_roundtrip():
    bits = [True, False, True, True, False, False, False, False, True, False]
    assert pack_bits(bits) == bytes([0b00001101, 0b00000001])
    assert unpack_bits(pack_bits(bits), len(bits)) == bits


def test_read_discrete_inputs():
    store = BitStore(9, 8)
    store.set_input(0, True)
    store.set_input(8, True)
    assert handle_pdu(store, bytes([2, 0, 0, 0, 9])) == bytes([2, 2, 0x01, 0x01])
    assert handle_pdu(store, bytes([2, 0, 8, 0, 1])) == bytes([2, 1, 0x01])


def test_write_multiple_coils_and_callback():
    store = BitStore(1, 8)
    seen = []
    store.on_coils_changed = seen.append
    resp = handle_pdu(store, bytes([15, 0, 0, 0, 8, 1, 0b10000001]))
    assert resp == bytes([15, 0, 0, 0, 8])
    assert store.coils() == [True] + [False] * 6 + [True]
    assert len(seen) == 1
    # 同じ値なら通知しない
    handle_pdu(store, bytes([15, 0, 0, 0, 8, 1, 0b10000001]))
    assert len(seen) == 1
    assert handle_pdu(store, bytes([1, 0, 0, 0, 8])) == bytes([1, 1, 0b10000001])


def test_write_single_coil():
    store = BitStore(1, 2)
    assert handle_pdu(store, bytes([5, 0, 1, 0xFF, 0])) == bytes([5, 0, 1, 0xFF, 0])
    assert store.coils() == [False, True]
    assert handle_pdu(store, bytes([5, 0, 1, 0x12, 0])) == bytes([0x85, 3])


@pytest.mark.parametrize('pdu, expected', [
    (bytes([2, 0, 5, 0, 10]), bytes([0x82, 2])),       # 範囲外
    (bytes([15, 0, 0, 0, 9, 2, 0, 0]), bytes([0x8F, 2])),
    (bytes([3, 0, 0, 0, 1]), bytes([0x83, 1])),        # 未対応のファンクション
    (bytes([2, 0, 0, 0, 0]), bytes([0x82, 3])),
])
def test_exceptions(pdu, expected):
    assert handle_pdu(BitStore(9, 8), pdu) == expected


def _request(sock, tid, unit, pdu):
    sock.sendall(struct.pack('>HHHB', tid, 0, len(pdu) + 1, unit) + pdu)
    header = sock.recv(7)
    rtid, pid, length, runit = struct.unpack('>HHHB', header)
    body = b''
    while len(body) < length - 1:
        body += sock.recv(length - 1 - len(body))
    assert (rtid, pid, runit) == (tid, 0, unit)
    return body


def test_tcp_server_roundtrip():
    store = BitStore(9, 8)
    store.set_input(3, True)
    server = ModbusTcpSlave(store, '127.0.0.1', 0, unit_id=1)
    server.start()
    try:
        port = server.server_address[1]
        with socket.create_connection(('127.0.0.1', port), timeout=2) as sock:
            assert _request(sock, 1, 1, bytes([2, 0, 0, 0, 9])) == bytes([2, 2, 0x08, 0x00])
            assert _request(sock, 2, 1, bytes([15, 0, 0, 0, 8, 1, 0x05])) == bytes([15, 0, 0, 0, 8])
        assert store.coils()[:3] == [True, False, True]
        assert server.last_request > float('-inf')
    finally:
        server.stop()
