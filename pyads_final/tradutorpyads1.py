import os
import pyads
import time
import numpy as np
from plc_parser import PlcParser
from plc_writer import PlcWriter
from app import app

# ---------------------------------------------------------------------------
# Configuracao
# ---------------------------------------------------------------------------
PLC_AMS    = '127.0.0.1.1.1'
PLC_PORT   = 851
ADDR_READ  = 0
ADDR_WRITE = 10000
BLOCK_SIZE = 10000

# ---------------------------------------------------------------------------
# Parser — carregado uma vez
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
parser   = PlcParser(os.path.join(BASE_DIR, "plcmap.yaml"))
writer = PlcWriter(os.path.join(BASE_DIR, "plcmap.yaml"))
# ---------------------------------------------------------------------------
# buffer_converter
# ---------------------------------------------------------------------------
_DTYPE_UINT16_LE = np.dtype("<u2")

def bytes_to_words(buffer: bytes | bytearray) -> np.ndarray:
    if len(buffer) % 2 != 0:
        raise ValueError(
            f"Buffer com tamanho impar ({len(buffer)} bytes). "
            "Cada word requer 2 bytes."
        )
    return np.frombuffer(buffer, dtype=_DTYPE_UINT16_LE)

# ---------------------------------------------------------------------------
# ADS — leitura e escrita
# ---------------------------------------------------------------------------
def read_buffer(plc) -> list[int]:
    raw = bytes(plc.read(
        index_group=0x4020,
        index_offset=ADDR_READ,
        plc_datatype=pyads.PLCTYPE_BYTE * BLOCK_SIZE
    ))
    return list(raw)

def write_buffer(plc, buffer: list[int]):
    raw   = bytes(buffer)
    ctype = pyads.PLCTYPE_BYTE * BLOCK_SIZE
    plc.write(
        index_group=0x4020,
        index_offset=ADDR_WRITE,
        value=ctype(*raw),
        plc_datatype=ctype
    )

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
x = 0  # alterar para o address q queremos verificar



def main():
    plc = pyads.Connection(PLC_AMS, PLC_PORT)
    plc.open()
    print('Ligado ao PLC')
    buffer_out = writer.default()

    try:
        while True:
            # --- leitura ---
            raw_bytes = bytes(read_buffer(plc))

            # words (original)
            buffer_in = bytes_to_words(raw_bytes)
            data_in    = parser.parse(raw_bytes)
            #print(f'BufferIn[exemplo]  = {buffer_in[x//2]}')

            # --- parse ---
            parser.display(data_in)

            # --- mirror ---
            #write_buffer(plc, list(raw_bytes))
            buffer_out = app(data_in, buffer_out)
            #parser.display(buffer_out)
            write_buffer(plc, list(writer.build(buffer_out)))

            #time.sleep(3)

    finally:
        plc.close()

if __name__ == '__main__':
    main()