#!/usr/bin/env python3
import os
import re
import json
import socket
import argparse
import functools
import subprocess
from datetime import datetime, timedelta


def running(func):
    @functools.wraps(func)
    def create_pid(*args, **kwargs):
        pid = str(os.getpid())
        location = os.path.dirname(os.path.realpath(__file__))
        location_pid = os.path.join(location, 'running.pid')
        if os.path.isfile(location_pid):
            with open(location_pid) as f:
                print('Script already running under PID {0}, skipping execution.'.format(f.read()))
            raise SystemExit(1)
        try:
            with open(location_pid, 'w') as f:
                f.write(pid)
            return func(*args, **kwargs)
        finally:
            os.unlink(location_pid)

    return create_pid


def run_command(command: list) -> dict:
    run = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = run.communicate()
    if run.returncode == 0:
        return {'status': True, 'message': out.decode('utf-8', 'replace').rstrip()}
    else:
        return {'status': False, 'message': err.decode('utf-8', 'replace').rstrip()}


def vm_is_stopped(vmid: str, virtualization: str) -> bool:
    run = run_command([virtualization, 'status', vmid])
    if run['status']:
        if 'stopped' in run['message'].lower():
            return True

    return False


def vmid_list(exclude: list, vmlist_path: str = '/etc/pve/.vmlist') -> dict:
    vm_id = {}
    node = socket.gethostname().split('.')[0]
    with open(vmlist_path) as vmlist:
        data = json.load(vmlist)
    for key, value in data['ids'].items():
        if value['type'] == 'lxc' and value['node'] == node and key not in exclude:
            vm_id[key] = 'pct'            
        elif value['type'] == 'qemu' and value['node'] == node and key not in exclude:
            vm_id[key] = 'qm'            
    return vm_id


def create_snapshot(vmid: str, virtualization: str, label: str = 'daily', mute: bool = False,
                    only_on_running: bool = False, savevmstate: bool = False, dryrun: bool = False):
    if only_on_running and vm_is_stopped(vmid, virtualization):
        print('VM {0} - status is stopped, skipping...'.format(vmid)) if not mute else None
        return

    name = {'hourly': 'autohourly', 'daily': 'autodaily', 'weekly': 'autoweekly', 'monthly': 'automonthly'}
    prefix = datetime.strftime(datetime.now() + timedelta(seconds=1), '%y%m%d%H%M%S')
    snapshot_name = name[label] + prefix
    params = [virtualization, 'snapshot', vmid, snapshot_name, '--description', 'autosnap']
    if virtualization == 'qm' and savevmstate:
        params.append('--vmstate')
    if dryrun:
        print(' '.join(params)) if not mute else None
    else:
        run = run_command(params)
        if run['status']:
            print('VM {0} - Creating snapshot {1}'.format(vmid, snapshot_name)) if not mute else None
        else:
            print('VM {0} - {1}'.format(vmid, run['message']))


def remove_snapshot(vmid: str, virtualization: str, label: str = 'daily', keep: int = 30, mute: bool = False,
                    only_on_running: bool = False, dryrun: bool = False):
    if only_on_running and vm_is_stopped(vmid, virtualization):
        print('VM {0} - status is stopped, skipping...'.format(vmid)) if not mute else None
        return

    listsnapshot = []
    snapshots = run_command([virtualization, 'listsnapshot', vmid])

    for snapshot in snapshots['message'].splitlines():
        snapshot = re.search(r'auto{0}\d+'.format(label), snapshot.replace('`->', '').split()[0])
        if snapshot is not None:
            listsnapshot.append(snapshot.group(0))

    if listsnapshot and len(listsnapshot) > keep:
        old_snapshots = [snap for num, snap in enumerate(sorted(listsnapshot, reverse=True), 1) if num > keep]
        if old_snapshots:
            for old_snapshot in old_snapshots:
                params = [virtualization, 'delsnapshot', vmid, old_snapshot]
                if dryrun:
                    print(' '.join(params)) if not mute else None
                else:
                    run = run_command(params)
                    if run['status']:
                        print('VM {0} - Removing snapshot {1}'.format(vmid, old_snapshot)) if not mute else None
                    else:
                        print('VM {0} - {1}'.format(vmid, run['message']))


@running
def main():
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
    parser.add_argument('-r', '--running', action='store_true', help='Run only on running vm, skip on stopped')
    parser.add_argument('-i', '--includevmstate', action='store_true', help='Include the VM state in snapshots.')
    parser.add_argument('-d', '--dryrun', action='store_true', help='Do not create or delete snapshots, just print the commands.')
    argp = parser.parse_args()
    all_vmid = vmid_list(exclude=argp.exclude)

    if argp.snap:
        if 'all' in argp.vmid:
            for k, v in all_vmid.items():
                create_snapshot(vmid=k, virtualization=v, label=argp.label, mute=argp.mute,
                                only_on_running=argp.running, savevmstate=argp.includevmstate, dryrun=argp.dryrun)
        else:
            for vm in argp.vmid:
                create_snapshot(vmid=vm, virtualization=all_vmid[vm], label=argp.label, mute=argp.mute,
                                only_on_running=argp.running, savevmstate=argp.includevmstate, dryrun=argp.dryrun)
    elif argp.clean:
        if 'all' in argp.vmid:
            for k, v in all_vmid.items():
                remove_snapshot(vmid=k, virtualization=v, label=argp.label, keep=argp.keep, mute=argp.mute,
                                only_on_running=argp.running, dryrun=argp.dryrun)
        else:
            for vm in argp.vmid:
                remove_snapshot(vmid=vm, virtualization=all_vmid[vm], label=argp.label, keep=argp.keep, mute=argp.mute,
                                only_on_running=argp.running, dryrun=argp.dryrun)
    elif argp.autosnap:
        if 'all' in argp.vmid:
            for k, v in all_vmid.items():
                create_snapshot(vmid=k, virtualization=v, label=argp.label, mute=argp.mute,
                                only_on_running=argp.running, savevmstate=argp.includevmstate, dryrun=argp.dryrun)
                remove_snapshot(vmid=k, virtualization=v, label=argp.label, keep=argp.keep, mute=argp.mute,
                                only_on_running=argp.running, dryrun=argp.dryrun)
        else:
            for vm in argp.vmid:
                create_snapshot(vmid=vm, virtualization=all_vmid[vm], label=argp.label, mute=argp.mute,
                                only_on_running=argp.running, savevmstate=argp.includevmstate, dryrun=argp.dryrun)
                remove_snapshot(vmid=vm, virtualization=all_vmid[vm], label=argp.label, keep=argp.keep, mute=argp.mute,
                                only_on_running=argp.running, dryrun=argp.dryrun)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
