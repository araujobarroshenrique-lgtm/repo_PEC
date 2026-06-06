"""
tmc_to_yaml.py
--------------
Gera plc_map.yaml a partir do ficheiro .tmc exportado pelo TwinCAT.

Suporta:
  - Tipos primitivos (BOOL, BYTE, INT, UINT, DINT, REAL, LREAL, ...)
  - BIT: bit individual dentro de um byte (com bit_number 0-7)
  - STRING(n)
  - Enums -> tratados como UINT
  - DATE_AND_TIME -> tratado como UDINT
  - Structs aninhadas (expansao recursiva ate profundidade 10)
  - Validacao de bounds e deteccao de overlaps

Uso:
    python tmc_to_yaml.py ficheiro.tmc
    python tmc_to_yaml.py ficheiro.tmc output.yaml
"""

import sys
import yaml
import xml.etree.ElementTree as ET

BLOCK_SIZE = 10000  # bytes por bloco (buffer_in e buffer_out)


# ---------------------------------------------------------------------------
# 1. Recolher structs e enums do .tmc
# ---------------------------------------------------------------------------

def collect_types(root):
    struct_defs = {}
    enum_defs   = set()

    for dt in root.findall('.//DataType'):
        name_el = dt.find('Name')
        if name_el is None:
            continue
        name = name_el.text

        if dt.find('.//EnumInfo') is not None:
            enum_defs.add(name)
            continue

        subitems = dt.findall('SubItem')
        if not subitems:
            continue

        fields = []
        for sub in subitems:
            sname    = sub.find('Name').text    if sub.find('Name')    is not None else '?'
            stype    = sub.find('Type').text    if sub.find('Type')    is not None else '?'
            sbitoffs = int(sub.find('BitOffs').text) if sub.find('BitOffs') is not None else 0
            sbitsize = int(sub.find('BitSize').text) if sub.find('BitSize') is not None else 0
            fields.append({
                'name':       sname,
                'type':       stype,
                'bit_offset': sbitoffs,
                'bit_size':   sbitsize,
            })
        struct_defs[name] = fields

    return struct_defs, enum_defs


# ---------------------------------------------------------------------------
# 2. Expandir struct recursivamente em lista plana de fields primitivos
# ---------------------------------------------------------------------------

def expand_fields(fields, struct_defs, depth=0):
    if depth > 10:
        return fields
    result = []
    for f in fields:
        ftype = f['type']
        if ftype in struct_defs:
            sub = expand_fields(struct_defs[ftype], struct_defs, depth + 1)
            for s in sub:
                result.append({
                    'name':       f['name'] + '_' + s['name'],
                    'type':       s['type'],
                    'bit_offset': f['bit_offset'] + s['bit_offset'],
                    'bit_size':   s['bit_size'],
                })
        else:
            result.append(dict(f))
    return result


# ---------------------------------------------------------------------------
# 3. Converter lista plana de fields em entradas YAML
# ---------------------------------------------------------------------------

def fields_to_entries(fields, base_bit_offset, prefix, enum_defs):
    entries = []
    for f in fields:
        abs_bit = base_bit_offset + f['bit_offset']
        ftype   = f['type']
        fname   = prefix + '_' + f['name'] if prefix else f['name']

        # Enum -> UINT
        if ftype in enum_defs:
            ftype = 'UINT'

        # STRING(n)
        if ftype.upper().startswith('STRING('):
            entries.append({
                'name':          fname,
                'type':          ftype.upper(),
                'byte_offset':   abs_bit // 8,
                'byte_size':     f['bit_size'] // 8,
                'string_length': int(ftype[7:-1]),
            })
            continue

        # BIT individual
        if ftype in ('BIT', 'BOOL') and f['bit_size'] == 1:
            entries.append({
                'name':        fname,
                'type':        'BIT',
                'byte_offset': abs_bit // 8,
                'byte_size':   1,
                'bit_number':  abs_bit % 8,
            })
            continue

        # DATE_AND_TIME -> UDINT
        if ftype == 'DATE_AND_TIME':
            entries.append({
                'name':        fname,
                'type':        'UDINT',
                'byte_offset': abs_bit // 8,
                'byte_size':   4,
            })
            continue

        # Primitivo normal
        byte_size = f['bit_size'] // 8
        if byte_size == 0:
            sys.stderr.write(f'AVISO: {fname} tipo {ftype} bitsize={f["bit_size"]} — ignorado\n')
            continue

        entries.append({
            'name':        fname,
            'type':        ftype,
            'byte_offset': abs_bit // 8,
            'byte_size':   byte_size,
        })

    return entries


# ---------------------------------------------------------------------------
# 4. Verificacoes de qualidade
# ---------------------------------------------------------------------------

def check_bounds(entries, label):
    for e in entries:
        end = e['byte_offset'] + e['byte_size']
        if end > BLOCK_SIZE:
            sys.stderr.write(
                f'AVISO [{label}]: "{e["name"]}" ultrapassa o bloco '
                f'(offset {e["byte_offset"]} + size {e["byte_size"]} = {end} > {BLOCK_SIZE})\n'
            )


def check_overlaps(entries, label):
    occupied = {}
    for e in entries:
        if e.get('type') == 'BIT':
            key = (e['byte_offset'], e.get('bit_number'))
            if key in occupied:
                sys.stderr.write(
                    f'AVISO [{label}]: bit {key} partilhado por '
                    f'"{occupied[key]}" e "{e["name"]}"\n'
                )
            occupied[key] = e['name']


# ---------------------------------------------------------------------------
# 5. Processar MArea
# ---------------------------------------------------------------------------

def parse_tmc(tmc_path):
    tree = ET.parse(tmc_path)
    root = tree.getroot()

    struct_defs, enum_defs = collect_types(root)

    buffer_in  = []
    buffer_out = []

    for area in root.findall('.//DataArea'):
        area_no = area.find('AreaNo')
        if area_no is None or area_no.get('AreaType') != 'MArea':
            continue

        for sym in area.findall('Symbol'):
            raw_name  = sym.find('Name').text
            base_type = sym.find('BaseType').text if sym.find('BaseType') is not None else '?'
            bitoffs   = int(sym.find('BitOffs').text)
            bitsize   = int(sym.find('BitSize').text)
            short     = raw_name.split('.')[-1]
            byte_off  = bitoffs // 8
            is_out    = byte_off >= BLOCK_SIZE
            norm_off  = byte_off - BLOCK_SIZE if is_out else byte_off
            target    = buffer_out if is_out else buffer_in

            # Struct conhecida -> expandir
            if base_type in struct_defs:
                expanded = expand_fields(struct_defs[base_type], struct_defs)
                entries  = fields_to_entries(expanded, bitoffs, short, enum_defs)
                for e in entries:
                    if is_out:
                        e['byte_offset'] -= BLOCK_SIZE
                    target.append(e)
                continue

            # Enum -> UINT
            if base_type in enum_defs:
                target.append({
                    'name':        short,
                    'type':        'UINT',
                    'byte_offset': norm_off,
                    'byte_size':   bitsize // 8,
                })
                continue

            # BIT individual
            if base_type == 'BIT' and bitsize == 1:
                target.append({
                    'name':        short,
                    'type':        'BIT',
                    'byte_offset': norm_off,
                    'byte_size':   1,
                    'bit_number':  bitoffs % 8,
                })
                continue

            # STRING(n)
            if base_type.upper().startswith('STRING('):
                target.append({
                    'name':          short,
                    'type':          base_type.upper(),
                    'byte_offset':   norm_off,
                    'byte_size':     bitsize // 8,
                    'string_length': int(base_type[7:-1]),
                })
                continue

            # Primitivo normal
            byte_size = bitsize // 8
            if byte_size == 0:
                sys.stderr.write(f'AVISO: {short} tipo {base_type} bitsize={bitsize} — ignorado\n')
                continue

            target.append({
                'name':        short,
                'type':        base_type,
                'byte_offset': norm_off,
                'byte_size':   byte_size,
            })

    check_bounds(buffer_in,  'buffer_in')
    check_bounds(buffer_out, 'buffer_out')
    check_overlaps(buffer_in,  'buffer_in')
    check_overlaps(buffer_out, 'buffer_out')

    return {'buffer_in': buffer_in, 'buffer_out': buffer_out}


# ---------------------------------------------------------------------------
# 6. Gerar YAML
# ---------------------------------------------------------------------------

def generate_yaml(tmc_path, out_path='plc_map.yaml'):
    data = parse_tmc(tmc_path)

    with open(out_path, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    print(f'Gerado: {out_path}')
    print(f'  buffer_in  entradas: {len(data["buffer_in"])}')
    print(f'  buffer_out entradas: {len(data["buffer_out"])}')


if __name__ == '__main__':
    # ── Caminhos por defeito — altera aqui quando mudas de projecto ──
    DEFAULT_TMC  = r"C:\Users\arauj\OneDrive\Área de Trabalho\tradutorpyads1\twincatestruturasdemerda\twincatestruturasdemerda\estruturamerda\estruturamerda.tmc"
    DEFAULT_YAML = r"C:\Users\arauj\OneDrive\Área de Trabalho\tradutorpyads1\Nova pasta\plc_map.yaml"

    if len(sys.argv) < 2:
        # Sem argumentos — usa os caminhos por defeito
        print(f'[INFO] A usar caminhos por defeito:')
        print(f'  TMC : {DEFAULT_TMC}')
        print(f'  YAML: {DEFAULT_YAML}')
        tmc = DEFAULT_TMC
        out = DEFAULT_YAML
    else:
        tmc = sys.argv[1]
        out = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_YAML

    generate_yaml(tmc, out)