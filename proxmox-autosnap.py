#!/usr/bin/env python3
import os
import re
import sys
import json
import socket
import argparse
import functools
import subprocess
from pathlib import Path
from datetime import datetime, timedelta


def running(func):
    @functools.wraps(func)
    def create_pid(*args, **kwargs):
        pid = str(os.getpid())
        location = Path(__file__).resolve().parent
        location_pid = str(location.joinpath('running.pid'))
        if os.path.isfile(location_pid):
            with open(location_pid, 'r') as f:
                print('Script already running under PID {0}, skipping execution.'.format(f.read()))
            sys.exit(1)
        try:
            with open(location_pid, 'w') as f:
                f.write(pid)
            return func(*args, **kwargs)
        finally:
            os.unlink(location_pid)
    return create_pid


def run_command(command_line: list):
    run = subprocess.Popen(command_line, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    out, err = run.communicate()
    if run.returncode == 0:
        return {'status': True, 'message': out.rstrip()}
    else:
        return {'status': False, 'message': err.rstrip()}


def vmid_list(exclude: list, vmlist_path: str = '/etc/pve/.vmlist'):
    vm_id = {}
    node = socket.gethostname()
    with open(vmlist_path, 'r') as vmlist:
        data = json.load(vmlist)
    for key, value in data['ids'].items():
        if value['type'] == 'lxc' and value['node'] == node and key not in exclude:
            vm_id[key] = 'pct'
        elif value['type'] == 'qemu' and value['node'] == node and key not in exclude:
            vm_id[key] = 'qm'
    return vm_id


@running
def create_snapshot(vmid: str, virtualization: str, label: str = 'daily', mute: bool = False):
    name = {'hourly': 'autohourly', 'daily': 'autodaily', 'weekly': 'autoweekly', 'monthly': 'automonthly'}
    prefix = datetime.strftime(datetime.now() + timedelta(seconds=1), '%y%m%d%H%M%S')
    snapshot_name = name[label] + prefix
    run = run_command([virtualization, 'snapshot', vmid, snapshot_name, '--description', 'autosnap'])
    if not run['status']:
        print('VM {0} - {1}'.format(vmid, run['message']))
    else:
        print('VM {0} - Creating snapshot {1}'.format(vmid, snapshot_name)) if not mute else None


@running
def remove_snapsot(vmid: str, virtualization: str, label: str = 'daily', keep: int = 30, mute: bool = False):
    listsnapshot = []
    snapshots = run_command([virtualization, 'listsnapshot', vmid])

    for snapshot in snapshots['message'].splitlines():
        snapshot = snapshot.split()[0]
        re_snapshot = re.search(label, snapshot)
        if re_snapshot is not None:
            listsnapshot.append(snapshot)

    if listsnapshot and len(listsnapshot) > keep:
        old_snapshots = []
        for num, snap in enumerate(sorted(listsnapshot, reverse=True), 1):
            if num > keep:
                old_snapshots.append(snap)
        if old_snapshots:
            for old_snapshot in old_snapshots:
                run = run_command([virtualization, 'delsnapshot', vmid, old_snapshot])
                if not run['status']:
                    print('VM {0} - {1}'.format(vmid, run['message']))
                else:
                    print('VM {0} - Removing snapshot {1}'.format(vmid, old_snapshot)) if not mute else None


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-a', '--autosnap', action='store_true', help='Create a snapshot and delete the old one.')
    parser.add_argument('-s', '--snap', action='store_true', help='Create a snapshot but do not delete anything.')
    parser.add_argument('-v', '--vmid', nargs='+', required=True,
                        help='Space separated list of CT/VM ID or all for all CT/VM in node.')
    parser.add_argument('-c', '--clean', action='store_true', help='Delete all or selected autosnapshots.')
    parser.add_argument('-k', '--keep', type=int, default=30, help='The number of snapshots which should will keep.')
    parser.add_argument('-l', '--label', choices=['hourly', 'daily', 'weekly', 'monthly'], default='daily',
                        help='One of hourly, daily, weekly, monthly.')
    parser.add_argument('-e', '--exclude', nargs='+', default=[],
                        help='Space separated list of CT/VM ID to exclude from processing.')
    parser.add_argument('-m', '--mute', action='store_true', help='Output only errors.')
    argp = parser.parse_args()
    all_vmid = vmid_list(argp.exclude)
    if argp.snap:
        if 'all' in argp.vmid:
            for k, v in all_vmid.items():
                create_snapshot(vmid=k, virtualization=v, label=argp.label, mute=argp.mute)
        else:
            for vm in argp.vmid:
                create_snapshot(vmid=vm, virtualization=all_vmid[vm], label=argp.label, mute=argp.mute)
    elif argp.clean:
        if 'all' in argp.vmid:
            for k, v in all_vmid.items():
                remove_snapsot(vmid=k, virtualization=v, label=argp.label, keep=argp.keep, mute=argp.mute)
        else:
            for vm in argp.vmid:
                remove_snapsot(vmid=vm, virtualization=all_vmid[vm], label=argp.label, keep=argp.keep, mute=argp.mute)
    elif argp.autosnap:
        if 'all' in argp.vmid:
            for k, v in all_vmid.items():
                create_snapshot(vmid=k, virtualization=v, label=argp.label, mute=argp.mute)
                remove_snapsot(vmid=k, virtualization=v, label=argp.label, keep=argp.keep, mute=argp.mute)
        else:
            for vm in argp.vmid:
                create_snapshot(vmid=vm, virtualization=all_vmid[vm], label=argp.label, mute=argp.mute)
                remove_snapsot(vmid=vm, virtualization=all_vmid[vm], label=argp.label, keep=argp.keep, mute=argp.mute)
    else:
        parser.print_help()
