"""
plc_parser.py
-------------
Faz parse de buffer_in (bytes) para dict Python usando plc_map.yaml.

Suporta tipos primitivos, STRING, e BIT (com bit_number).
"""

import struct
import logging
import yaml
from typing import Any

log = logging.getLogger(__name__)

_FMT = {
    'BOOL':  '<B',
    'BYTE':  '<B',
    'USINT': '<B',
    'SINT':  '<b',
    'UINT':  '<H',
    'INT':   '<h',
    'WORD':  '<H',
    'UDINT': '<I',
    'DINT':  '<i',
    'DWORD': '<I',
    'ULINT': '<Q',
    'LINT':  '<q',
    'REAL':  '<f',
    'LREAL': '<d',
    'TIME':  '<I',
    'DATE_AND_TIME': '<I',
}

BLOCK_SIZE = 10000


def _decode(buf, sym):
    t    = sym['type']
    off  = sym['byte_offset']
    size = sym['byte_size']

    if t == 'BIT':
        byte_val = buf[off]
        bit_num  = sym.get('bit_number', 0)
        return bool((byte_val >> bit_num) & 1)

    if t.startswith('STRING('):
        return buf[off:off+size].rstrip(b'\x00').decode('utf-8', errors='replace')

    if t == 'BOOL':
        return bool(buf[off])

    fmt = _FMT.get(t)
    if fmt is None:
        log.warning("Tipo desconhecido '%s' em '%s' — devolvido None", t, sym.get('name','?'))
        return None

    return struct.unpack_from(fmt, buf, off)[0]


class PlcParser:
    def __init__(self, map_path='plc_map.yaml'):
        with open(map_path, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f)
        self._map = cfg['buffer_in']

    def parse(self, buf: bytes) -> dict:
        if len(buf) < BLOCK_SIZE:
            raise ValueError(f'Buffer demasiado pequeno: {len(buf)} bytes (minimo: {BLOCK_SIZE})')
        return {sym['name']: _decode(buf, sym) for sym in self._map}

    def display(self, data: dict, indent: int = 0) -> None:
        pad = '  ' * indent
        for key, val in data.items():
            if isinstance(val, dict):
                print(f'{pad}{key}:')
                self.display(val, indent + 1)
            elif isinstance(val, float):
                print(f'{pad}{key}: {val:.6f}')
            else:
                print(f'{pad}{key}: {val}')