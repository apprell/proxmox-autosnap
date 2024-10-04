#!/usr/bin/env python3
import os
import re
import json
import socket
import argparse
import functools
import subprocess
from datetime import datetime, timedelta

MUTE = False
DRY_RUN = False
USE_SUDO = False
ONLY_ON_RUNNING = False
DATE_ISO_FORMAT = False
DATE_TRUENAS_FORMAT = False
INCLUDE_VM_STATE = False


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


def run_command(command: list, force_no_sudo: bool = False) -> dict:
    if USE_SUDO and not force_no_sudo:
        command.insert(0, 'sudo')

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


def get_pve_config(vmid: str, virtualization: str) -> dict:
    run = run_command([virtualization, 'config', vmid])
    if not run['status']:
        raise SystemExit(run['message'])

    cfg = {}

    for line in run['message'].splitlines():
        if ':' in line:
            (k, v) = line.split(': ')
            cfg[k.strip()] = v.strip()

    return cfg


def get_zfs_volume(proxmox_fs: str, virtualization: str) -> str:
    run = run_command(['pvesm', 'path', proxmox_fs.split(',')[0]])
    if not run['status']:
        raise SystemExit(run['message'])

    zfsvol = run['message'].strip()
    if virtualization == 'qm' and zfsvol.startswith('/dev/zvol/'):
        return zfsvol.removeprefix('/dev/zvol/')
    elif zfsvol[0] == '/':
        return zfsvol[1:]
    else:
        return zfsvol


def vmid_list(exclude: list, vmlist_path: str = '/etc/pve/.vmlist') -> dict:
    vm_id = {}
    node = socket.gethostname().split('.')[0]

    run = run_command(['cat', vmlist_path])
    if not run['status']:
        raise SystemExit(run['message'])

    data = json.loads(run['message'])
    for key, value in data['ids'].items():
        if value['type'] == 'lxc' and value['node'] == node and key not in exclude:
            vm_id[key] = 'pct'
        elif value['type'] == 'qemu' and value['node'] == node and key not in exclude:
            vm_id[key] = 'qm'

    return vm_id


def create_snapshot(vmid: str, virtualization: str, label: str = 'daily') -> None:
    if ONLY_ON_RUNNING and vm_is_stopped(vmid, virtualization):
        print('VM {0} - status is stopped, skipping...'.format(vmid)) if not MUTE else None
        return

    labels = {'minute': 'autominute', 'hourly': 'autohourly', 'daily': 'autodaily', 'weekly': 'autoweekly',
              'monthly': 'automonthly'}
    suffix_datetime = datetime.now() + timedelta(seconds=1)
    if DATE_ISO_FORMAT:
        suffix = '_' + suffix_datetime.isoformat(timespec='seconds').replace('-', '_').replace(':', '_')
    elif DATE_TRUENAS_FORMAT:
        suffix = suffix_datetime.strftime('%Y%m%d%H%M%S')
    else:
        suffix = suffix_datetime.strftime('%y%m%d%H%M%S')
    snapshot_name = labels[label] + suffix
    params = [virtualization, 'snapshot', vmid, snapshot_name, '--description', 'autosnap']

    if virtualization == 'qm' and INCLUDE_VM_STATE:
        params.append('--vmstate')

    if DRY_RUN:
        params.insert(0, 'sudo') if USE_SUDO else None
        print(' '.join(params))
    else:
        run = run_command(params)
        if run['status']:
            print('VM {0} - Creating snapshot {1}'.format(vmid, snapshot_name)) if not MUTE else None
        else:
            print('VM {0} - {1}'.format(vmid, run['message']))


def remove_snapshot(vmid: str, virtualization: str, label: str = 'daily', keep: int = 30) -> None:
    if ONLY_ON_RUNNING and vm_is_stopped(vmid, virtualization):
        print('VM {0} - status is stopped, skipping...'.format(vmid)) if not MUTE else None
        return

    listsnapshot = []
    snapshots = run_command([virtualization, 'listsnapshot', vmid])

    for snapshot in snapshots['message'].splitlines():
        snapshot = re.search(r'auto{0}([_0-9T]+$)'.format(label), snapshot.replace('`->', '').split()[0])
        if snapshot is not None:
            listsnapshot.append(snapshot.group(0))

    if listsnapshot and len(listsnapshot) > keep:
        old_snapshots = [snap for num, snap in enumerate(sorted(listsnapshot, reverse=True), 1) if num > keep]
        if old_snapshots:
            for old_snapshot in old_snapshots:
                params = [virtualization, 'delsnapshot', vmid, old_snapshot]
                if DRY_RUN:
                    params.insert(0, 'sudo') if USE_SUDO else None
                    print(' '.join(params))
                else:
                    run = run_command(params)
                    if run['status']:
                        print('VM {0} - Removing snapshot {1}'.format(vmid, old_snapshot)) if not MUTE else None
                    else:
                        print('VM {0} - {1}'.format(vmid, run['message']))


def zfs_send(vmid: str, virtualization: str, zfs_send_to: str):
    cfg = get_pve_config(vmid, virtualization)

    for k, v in cfg.items():
        if (k == 'rootfs' or
                (re.fullmatch('mp[0-9]+', k) and ('backup=1' in v)) or
                (re.fullmatch('(ide|sata|scsi|virtio)[0-9]+', k) and ('backup=0' not in v)) or
                (re.fullmatch('(efidisk|tpmstate)[0-9]+', k))):

            proxmox_vol = v.split(',')[0]
            localzfs = get_zfs_volume(proxmox_vol, virtualization)
            remotezfs = os.path.join(zfs_send_to, proxmox_vol.split(':')[1])

            params = ['/usr/sbin/syncoid', localzfs, remotezfs, '--identifier=autosnap', '--no-privilege-elevation']
            if DRY_RUN:
                print(' '.join(params))
            else:
                run = run_command(params, force_no_sudo=True)
                if run['status']:
                    print('VM {0} - syncoid to {1}'.format(vmid, zfs_send_to)) if not MUTE else None
                else:
                    print('VM {0} - syncoid FAIL: {1}'.format(vmid, run['message']))


@running
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-a', '--autosnap', action='store_true', help='Create a snapshot and delete the old one.')
    parser.add_argument('-s', '--snap', action='store_true', help='Create a snapshot but do not delete anything.')
    parser.add_argument('-v', '--vmid', nargs='+', required=True,
                        help='Space separated list of CT/VM ID or all for all CT/VM in node.')
    parser.add_argument('-c', '--clean', action='store_true', help='Delete all or selected autosnapshots.')
    parser.add_argument('-k', '--keep', type=int, default=30, help='The number of snapshots which should will keep.')
    parser.add_argument('-l', '--label', choices=['minute', 'hourly', 'daily', 'weekly', 'monthly'], default='daily',
                        help='One of minute, hourly, daily, weekly or monthly.')
    parser.add_argument('--date-iso-format', action='store_true', help='Store snapshots in ISO 8601 format.')
    parser.add_argument('--date-truenas-format', action='store_true', help='Store snapshots in TrueNAS format.')
    parser.add_argument('-e', '--exclude', nargs='+', default=[],
                        help='Space separated list of CT/VM ID to exclude from processing.')
    parser.add_argument('-m', '--mute', action='store_true', help='Output only errors.')
    parser.add_argument('-r', '--running', action='store_true', help='Run only on running vm, skip on stopped')
    parser.add_argument('-i', '--includevmstate', action='store_true', help='Include the VM state in snapshots.')
    parser.add_argument('--zfs-send-to', metavar='[USER@]HOST:ZFSDIR',
                        help='Send zfs snapshot to USER@HOST on ZFSDIR hierarchy - USER@ is optional with syncoid > 2:1')
    parser.add_argument('-d', '--dryrun', action='store_true',
                        help='Do not create or delete snapshots, just print the commands.')
    parser.add_argument('--sudo', action='store_true', help='Launch commands through sudo.')
    argp = parser.parse_args()

    global MUTE, DRY_RUN, USE_SUDO, ONLY_ON_RUNNING, INCLUDE_VM_STATE, DATE_ISO_FORMAT, DATE_TRUENAS_FORMAT
    MUTE = argp.mute
    DRY_RUN = argp.dryrun
    USE_SUDO = argp.sudo
    ONLY_ON_RUNNING = argp.running
    DATE_ISO_FORMAT = argp.date_iso_format
    DATE_TRUENAS_FORMAT = argp.date_truenas_format
    INCLUDE_VM_STATE = argp.includevmstate

    all_vmid = vmid_list(exclude=argp.exclude)

    if 'all' in argp.vmid:
        picked_vmid = dict(sorted(all_vmid.items()))
    else:
        picked_vmid = {}
        for vm in argp.vmid:
            picked_vmid[vm] = all_vmid[vm]

    if argp.snap:
        for k, v in picked_vmid.items():
            create_snapshot(vmid=k, virtualization=v, label=argp.label)
    elif argp.clean:
        for k, v in picked_vmid.items():
            remove_snapshot(vmid=k, virtualization=v, label=argp.label, keep=argp.keep)
    elif argp.autosnap:
        for k, v in picked_vmid.items():
            create_snapshot(vmid=k, virtualization=v, label=argp.label)
            remove_snapshot(vmid=k, virtualization=v, label=argp.label, keep=argp.keep)
    elif argp.zfs_send_to:
        for k, v in picked_vmid.items():
            zfs_send(vmid=k, virtualization=v, zfs_send_to=argp.zfs_send_to)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
