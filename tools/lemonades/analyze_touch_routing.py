#!/usr/bin/env python3
"""Correlate pinned BackBoard logs with synthetic bridge identities.

This is a diagnostic stage, never a claim of app delivery, hardware identity,
Apple authentication, full iOS, or rendering. Truncated/ambiguous logs fail closed.
"""
import argparse
import json
import re
from pathlib import Path


def analyze(log, integrated):
    identities = re.findall(r'BRIDGE TEST (initial|restarted) pid=(\d+) service=(\d+)', log)
    rows = []
    # Ignore unrelated kernel/launchd strings and require an actual BackBoard
    # line. The bootstrap probe copies the original daemon's log with this prefix.
    lines = [line for line in log.splitlines() if line.startswith('BACKBOARD LOG | ') and '[TouchEvents]' in line]
    for phase, pid, number in identities:
        sender = format(int(number), 'X')
        attached = [i for i, line in enumerate(lines) if re.search(
            r'digitizer attached \(sender '+sender+r'\)', line, re.I)]
        row = {'phase': phase, 'pid': int(pid), 'sender': sender, 'observed': False}
        if len(attached) != 1:
            row['reason'] = 'missing or duplicate attachment'
            rows.append(row)
            continue
        start = attached[0]
        end = next((i for i in range(start+1, len(lines)) if 'digitizer attached (sender ' in lines[i]), len(lines))
        segment = lines[start:end]
        detached = [i for i, line in enumerate(segment) if re.search(
            r'digitizer detached \(sender '+sender+r'\)', line, re.I)]
        # Contact log lines have no sender. Require a single-service interval:
        # no other attachment/detachment may overlap this observation.
        own_removed = len(detached) == 1
        overlap = any('digitizer detached (sender ' in line and not re.search(
            r'digitizer detached \(sender '+sender+r'\)', line, re.I) for line in segment)
        prior_active = set()
        for line in lines[:start]:
            match = re.search(r'digitizer (attached|detached) \(sender ([0-9A-F]+)\)', line, re.I)
            if match:
                if match[1] == 'attached': prior_active.add(match[2].upper())
                else: prior_active.discard(match[2].upper())
        life = segment[:detached[0]] if own_removed else []
        unsupported = any('ignoring digitizer event for display <main> from unsupported service:' in line and
            re.search(r'senderID: 0x'+sender+r'\b', line, re.I) for line in life)
        declared = 'builtIn: YES' if integrated else 'builtIn: NO'
        profile = declared in segment[0] and 'transport:Virtual' in segment[0]
        touch = next((i for i, line in enumerate(life) if 'contact 1 presence: touching' in line), -1)
        release = next((i for i, line in enumerate(life) if 'contact 1 presence: none' in line), -1)
        acquired = any('*** acquired main display digitizer ' in line for line in life)
        # Forced bridge death must cancel its held contact; the clean restart
        # must explicitly release it before removal. Both are separate evidence.
        cancelled = any('cancel -- digitizer did disappear:' in line and
            re.search(r'senderID: 0x'+sender+r'\b', line, re.I) and 'touchIdentifier: 1; touching;' in line
            for line in segment)
        row.update(profile_matches=profile, removed=own_removed,
                   unambiguous=not overlap and not prior_active,
                   unsupported_main=unsupported, acquired_main=acquired,
                   touch_observed=touch >= 0, release_observed=0 <= touch < release,
                   held_contact_cancelled=cancelled)
        if integrated:
            row['observed'] = profile and own_removed and not overlap and not prior_active and not unsupported and acquired and touch >= 0 and (
                cancelled if phase == 'initial' else 0 <= touch < release)
        else:
            row['observed'] = profile and own_removed and not overlap and not prior_active and unsupported and not acquired and touch < 0
        rows.append(row)
    unique = len({r['pid'] for r in rows}) == 2 and len({r['sender'] for r in rows}) == 2 and all(r['pid'] > 1 and int(r['sender'],16)>0 for r in rows)
    complete = unique and len(rows) == 2 and [r['phase'] for r in rows] == ['initial', 'restarted'] and all(r['observed'] for r in rows)
    return {'scope': 'synthetic BackBoard routing observation only; app delivery and physical hardware not verified',
            'simulated_integrated_touch': bool(integrated), 'routing_observed': complete,
            'app_delivery_verified': False, 'physical_input_verified': False, 'services': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--simulated-integrated', action='store_true')
    args = parser.parse_args()
    result = analyze(args.log.read_text(errors='replace'), args.simulated_integrated)
    print(json.dumps(result, indent=2))
    return 0 if result['routing_observed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
