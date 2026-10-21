"""Teltonika TCP protocol: framing (used by the listener) and AVL decoding (used by the decoder).

Session on TCP:
  1. Device sends IMEI:  2-byte length + ASCII IMEI.   Server replies 0x01 (accept) / 0x00 (reject).
  2. Device sends AVL data packets:
       4 bytes  preamble (0x00000000)
       4 bytes  data field length  (codec id .. number-of-data-2)
       N bytes  data field: codec id (1), number of data 1 (1), records…, number of data 2 (1)
       4 bytes  CRC-16/IBM over the data field
     Server replies with the number of accepted records as a 4-byte big-endian int.

Codecs 8 and 8 Extended are decoded; other codecs are stored raw and marked unsupported.
Reference: https://wiki.teltonika-gps.com/view/Teltonika_Data_Sending_Protocols
"""
import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

CODEC_8 = 0x08
CODEC_8E = 0x8E
SUPPORTED_CODECS = {CODEC_8, CODEC_8E}

MAX_DATA_LENGTH = 1 << 16  # guard against garbage length fields


class ProtocolError(ValueError):
    pass


def crc16_ibm(data: bytes) -> int:
    """CRC-16/IBM (a.k.a. ARC): poly 0xA001 reflected, init 0x0000."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def parse_imei(frame: bytes) -> str:
    """Parse the IMEI handshake (2-byte length + ASCII digits)."""
    if len(frame) < 2:
        raise ProtocolError("IMEI frame too short")
    (length,) = struct.unpack(">H", frame[:2])
    imei = frame[2:2 + length]
    if len(imei) != length or not imei.isdigit():
        raise ProtocolError("Invalid IMEI frame")
    return imei.decode("ascii")


@dataclass
class AvlPacket:
    """A framed AVL packet as received on the wire (data field not yet decoded)."""
    raw: bytes            # full packet: preamble .. CRC
    codec: int
    record_count: int


def parse_avl_header(header: bytes) -> int:
    """Given the first 8 bytes of a packet, return the data field length."""
    preamble, length = struct.unpack(">II", header)
    if preamble != 0:
        raise ProtocolError("Bad preamble")
    if not 3 <= length <= MAX_DATA_LENGTH:
        raise ProtocolError(f"Unreasonable data length {length}")
    return length


def frame_avl_packet(raw: bytes) -> AvlPacket:
    """Validate a complete packet (header + data + CRC) and return its codec and record count."""
    length = parse_avl_header(raw[:8])
    if len(raw) != 8 + length + 4:
        raise ProtocolError("Packet length mismatch")
    data = raw[8:8 + length]
    (crc,) = struct.unpack(">I", raw[8 + length:])
    if crc16_ibm(data) != crc:
        raise ProtocolError("CRC mismatch")
    codec, count_1, count_2 = data[0], data[1], data[-1]
    if count_1 != count_2:
        raise ProtocolError("Record count mismatch")
    return AvlPacket(raw=raw, codec=codec, record_count=count_1)


@dataclass
class AvlRecord:
    timestamp: datetime
    priority: int
    longitude: float
    latitude: float
    altitude: int
    angle: int
    satellites: int
    speed: int                    # km/h
    event_io_id: int              # 0 = periodic record
    io: dict = field(default_factory=dict)  # {io_id: int | hex str}

    @property
    def has_fix(self) -> bool:
        return self.satellites > 0 and not (self.latitude == 0 and self.longitude == 0)


class _Reader:
    def __init__(self, data: bytes):
        self.data, self.pos = data, 0

    def take(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise ProtocolError("Truncated AVL data")
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def uint(self, n: int) -> int:
        return int.from_bytes(self.take(n), "big")

    def sint(self, n: int) -> int:
        return int.from_bytes(self.take(n), "big", signed=True)


def decode_avl_packet(raw: bytes) -> tuple[int, list[AvlRecord]]:
    """Decode a full Codec 8 / 8E packet into records. Returns (codec, records)."""
    packet = frame_avl_packet(raw)
    if packet.codec not in SUPPORTED_CODECS:
        raise ProtocolError(f"Unsupported codec 0x{packet.codec:02X}")
    extended = packet.codec == CODEC_8E
    id_size = 2 if extended else 1
    r = _Reader(raw[8:-4])
    r.take(2)  # codec id, number of data 1

    records = []
    for _ in range(packet.record_count):
        ts = datetime.fromtimestamp(r.uint(8) / 1000, tz=timezone.utc)
        priority = r.uint(1)
        longitude = r.sint(4) / 1e7
        latitude = r.sint(4) / 1e7
        altitude = r.sint(2)
        angle = r.uint(2)
        satellites = r.uint(1)
        speed = r.uint(2)
        event_io_id = r.uint(id_size)
        r.uint(id_size)  # total IO count

        io: dict = {}
        for value_size in (1, 2, 4, 8):
            for _ in range(r.uint(id_size)):
                io_id = r.uint(id_size)
                io[io_id] = r.uint(value_size)
        if extended:
            for _ in range(r.uint(2)):
                io_id = r.uint(2)
                io[io_id] = r.take(r.uint(2)).hex()

        records.append(AvlRecord(ts, priority, longitude, latitude, altitude, angle,
                                 satellites, speed, event_io_id, io))
    return packet.codec, records


def classify_event(record: AvlRecord) -> Optional[str]:
    """Our event code for a record (see app.dataprofiler.dictionary.EVENTS)."""
    from app.dataprofiler.dictionary import classify
    return classify(record.event_io_id, record.io)
