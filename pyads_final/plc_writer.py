"""
plc_writer.py
-------------
Constroi buffer_out (bytearray) a partir de um dict de valores.

Suporta tipos primitivos, STRING, e BIT (com bit_number).
BITs no mesmo byte sao acumulados com OR — nao se apagam mutuamente.
"""

import math
import struct
import logging
import yaml
from typing import Any

log = logging.getLogger(__name__)

BLOCK_SIZE = 10000

_FMT = {
    'BOOL':  ('<B', 0,   1),
    'BYTE':  ('<B', 0,   255),
    'USINT': ('<B', 0,   255),
    'SINT':  ('<b', -128, 127),
    'UINT':  ('<H', 0,   65535),
    'INT':   ('<h', -32768, 32767),
    'WORD':  ('<H', 0,   65535),
    'UDINT': ('<I', 0,   4_294_967_295),
    'DINT':  ('<i', -2_147_483_648, 2_147_483_647),
    'DWORD': ('<I', 0,   4_294_967_295),
    'ULINT': ('<Q', 0,   18_446_744_073_709_551_615),
    'LINT':  ('<q', -9_223_372_036_854_775_808, 9_223_372_036_854_775_807),
    'REAL':  ('<f', None, None),
    'LREAL': ('<d', None, None),
    'TIME':          ('<I', 0, 4_294_967_295),
    'DATE_AND_TIME': ('<I', 0, 4_294_967_295),
}


def _encode(buf: bytearray, sym: dict, value: Any) -> None:
    t    = sym['type']
    off  = sym['byte_offset']
    size = sym['byte_size']
    name = sym.get('name', '?')

    # BIT: set ou clear o bit especifico sem tocar nos outros bits do byte
    if t == 'BIT':
        bit_num = sym.get('bit_number', 0)
        if value:
            buf[off] |= (1 << bit_num)
        else:
            buf[off] &= ~(1 << bit_num)
        return

    # STRING
    if t.startswith('STRING('):
        encoded = str(value).encode('utf-8', errors='replace')
        if len(encoded) > size:
            log.warning("STRING truncado em '%s': %d→%d bytes", name, len(encoded), size)
        buf[off:off+size] = encoded[:size].ljust(size, b'\x00')
        return

    # BOOL
    if t == 'BOOL':
        buf[off] = 1 if value else 0
        return

    entry = _FMT.get(t)
    if entry is None:
        log.warning("Tipo desconhecido '%s' em '%s' — escrito zeros", t, name)
        return

    fmt, lo, hi = entry

    # Float: rejeitar NaN/inf
    if t in ('REAL', 'LREAL'):
        if not isinstance(value, (int, float)) or math.isnan(value) or math.isinf(value):
            log.error("Valor invalido (%s) em '%s' — escrito zero", value, name)
            buf[off:off+size] = b'\x00' * size
            return
        struct.pack_into(fmt, buf, off, float(value))
        return

    # Inteiro: clamp de overflow
    value = int(value)
    if lo is not None and value < lo or hi is not None and value > hi:
        clamped = max(lo, min(hi, value))
        log.warning("Overflow em '%s': %d → clamp para %d", name, value, clamped)
        value = clamped

    struct.pack_into(fmt, buf, off, value)


class PlcWriter:
    def __init__(self, map_path='plc_map.yaml', buffer_size=BLOCK_SIZE):
        with open(map_path, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f)
        self._map         = cfg['buffer_out']
        self._buffer_size = buffer_size

    def default(self) -> dict:
        """
        Devolve dict com todas as variaveis do buffer_out a zero.
        O developer altera só o que precisa e passa ao build().

        Exemplo:
            data_out = writer.default()
            data_out["movex"]    = data["posx"] + 1
            data_out["speedcmd"] = data["speed"] * 3
            write_buffer(plc, list(writer.build(data_out)))
        """
        result = {}
        for sym in self._map:
            t    = sym['type']
            name = sym['name']
            if t.startswith('STRING('):
                result[name] = ''
            elif t == 'BIT':
                result[name] = False
            elif t == 'BOOL':
                result[name] = False
            elif t in ('REAL', 'LREAL'):
                result[name] = 0.0
            else:
                result[name] = 0
        return result

    def default_from(self, parsed_in: dict) -> dict:
        """
        Devolve dict do buffer_out preenchido com valores do buffer_in
        onde os nomes coincidam — variaveis sem correspondencia ficam a zero.

        Util para mirror selectivo: copias o que queres e altereas o resto.

        Exemplo:
            data_out = writer.default_from(data)
            data_out["movex"] = data["posx"] + 1
            write_buffer(plc, list(writer.build(data_out)))
        """
        result = self.default()
        for name in result:
            if name in parsed_in:
                result[name] = parsed_in[name]
        return result

    def build(self, values: dict) -> bytearray:
        """
        Constroi buffer_out com os valores fornecidos.
        Campos nao incluidos ficam a zero.
        BITs no mesmo byte sao acumulados correctamente.
        """
        buf = bytearray(self._buffer_size)
        for sym in self._map:
            name = sym['name']
            if name not in values:
                continue
            try:
                _encode(buf, sym, values[name])
            except Exception as e:
                log.error("Erro ao escrever '%s': %s", name, e)
        return buf