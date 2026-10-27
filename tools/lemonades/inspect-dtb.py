#!/usr/bin/env python3
"""Read hardware evidence from a flattened tree; never write to a device."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def inspect(path):
    def get(node, prop, kind='x'):
        result = subprocess.run(['fdtget', '-t', kind, str(path), node, prop], capture_output=True, text=True)
        if result.returncode:
            return None
        return result.stdout.strip() if kind == 's' else [int(v, 16) for v in result.stdout.split()]

    def children(node):
        result = subprocess.run(['fdtget', '-l', str(path), node], capture_output=True, text=True, check=True)
        return result.stdout.splitlines()

    gic = get('/__symbols__', 'intc', 's') or '/soc/interrupt-controller@17a00000'
    i2c = get('/__symbols__', 'qupv3_se13_i2c', 's') or '/soc/i2c@a94000'
    # Stock uses synaptics_20828@4B; LineageOS uses synaptics@4B.
    # Match the compatible string, not a source-tree-specific node spelling.
    touch_nodes = [i2c + '/' + name for name in children(i2c)
                   if get(i2c + '/' + name, 'compatible', 's') == 'synaptics-s3908']
    touch = touch_nodes[0] if len(touch_nodes) == 1 else i2c + '/__unresolved_touch__'
    cpus = [{'node': '/cpus/' + name, 'mpidr': get('/cpus/' + name, 'reg'),
             'capacity': get('/cpus/' + name, 'capacity-dmips-mhz'),
             'compatible': get('/cpus/' + name, 'compatible', 's')}
            for name in children('/cpus') if name.startswith('cpu@')]
    reserved = [{'node': '/reserved-memory/' + name,
                 'reg': get('/reserved-memory/' + name, 'reg'),
                 'size': get('/reserved-memory/' + name, 'size'),
                 'status': get('/reserved-memory/' + name, 'status', 's')}
                for name in children('/reserved-memory')]
    return {'input': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'note': 'Source/firmware evidence only; does not establish that this DTB belongs to a connected phone.',
            'model': get('/', 'model', 's'), 'compatible': get('/', 'compatible', 's'),
            'msm_id': get('/', 'qcom,msm-id'), 'board_id': get('/', 'qcom,board-id'),
            'oplus_project': get('/', 'oplus,dtsi_no'), 'pcb_range': get('/', 'oplus,pcb_range'),
            'cpus': cpus, 'gic': {'node': gic, 'reg': get(gic, 'reg'),
                                'redistributor_stride': get(gic, 'redistributor-stride')},
            'touch': {'node': touch, 'compatible': get(touch, 'compatible', 's'),
                      'matching_nodes': touch_nodes,
                      'i2c_reg': get(i2c, 'reg'), 'address': get(touch, 'reg'),
                      'irq_gpio': get(touch, 'irq-gpio'), 'reset_gpio': get(touch, 'reset-gpio'),
                      'coordinates': get(touch, 'touchpanel,panel-coords')},
            'reserved_memory': reserved}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('dtb', type=Path)
    ap.add_argument('--output', type=Path)
    args = ap.parse_args()
    report = json.dumps(inspect(args.dtb.resolve()), indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report)
        print(args.output)
    else:
        print(report, end='')


if __name__ == '__main__':
    main()
