"""Generate a candidate Mu memory map from reviewed 9R stock configuration facts."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / 'uefi/lemonades/stock-memory.json'


def load():
    return json.loads(PROFILE.read_text())


def regions(profile):
    # Preserve Mu's existing early HYP reservation. Stock also declares IPC SHM
    # inside its unusable-DDR window. Do not introduce overlapping descriptors;
    # keep this subregion reserved pending SEC/SMEM initialization review.
    rows = [{'name': 'HYP', 'address': 0x80000000, 'size': 0x600000,
             'attributes': ['AddMem', 'SYS_MEM', 'SYS_MEM_CAP', 'Reserv', 'NS_DEVICE'],
             'section': 'MemoryMap'}]
    rows += [row for row in profile['stock_regions'] if row['name'] != 'IPC SHM']
    ram = sorted((r['address'], r['address'] + r['size']) for r in rows if r['section'] == 'MemoryMap')
    if any(end > next_start for (_, end), (next_start, _) in zip(ram, ram[1:])):
        raise ValueError('candidate RAM descriptors overlap')
    return rows


def source(profile):
    lines = ['/* Candidate 9R map derived from stock-memory.json; not boot-validated.',
             ' * IPC SHM stays inside Mu HYP reservation pending early-init review. */',
             '#include <Library/MemoryMapLib.h>', '',
             'STATIC EFI_MEMORY_REGION_DESCRIPTOR gMemoryDescriptor[] = {']
    for row in regions(profile):
        lines.append('  {"%s", 0x%08X, 0x%08X, %s},' %
                     (row['name'], row['address'], row['size'], ', '.join(row['attributes'])))
    lines += ['};', '', 'VOID GetMemoryMap (',
              '  OUT EFI_MEMORY_REGION_DESCRIPTOR **MemoryDescriptor,',
              '  OUT UINT8 *MemoryDescriptorCount)', '{',
              '  *MemoryDescriptor = gMemoryDescriptor;',
              '  *MemoryDescriptorCount = ARRAY_SIZE (gMemoryDescriptor);', '}', '']
    return '\n'.join(lines)
